import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

BASE_DIR = Path(__file__).resolve().parent
SELLERS_FILE = BASE_DIR / "sellers.json"
STATE_FILE = BASE_DIR / "state.json"
REPORT_FILE = BASE_DIR / "reporte_latest.md"
SCRAPFLY_ENDPOINT = "https://api.scrapfly.io/scrape"
MELI_SEARCH_ENDPOINT = "https://api.mercadolibre.com/sites/MLU/search"
PAGE_SIZE = 50

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def load_json_file(path, default_value):
    if not path.exists():
        return default_value
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        logging.warning("No se pudo parsear %s, usando valor por defecto", path.name)
        return default_value


def save_json_file(path, data):
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def normalize_price(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number.is_integer():
        return int(number)
    return round(number, 2)


def format_price(value):
    if value is None or value == "":
        return "sin precio"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def extract_seller_id(seller):
    seller_id = seller.get("seller_id")
    if seller_id:
        return str(seller_id)
    seller_url = seller.get("seller_url", "")
    match = re.search(r"_CustId_(\d+)", seller_url)
    if match:
        return match.group(1)
    raise ValueError(f"No se pudo extraer seller_id desde seller_url: {seller_url}")


def fetch_json_via_scrapfly(url, scrapfly_key):
    params = urlencode(
        {
            "key": scrapfly_key,
            "url": url,
            "country": "uy",
            "retry": "true",
            "proxified_response": "true",
            "format": "json",
        }
    )
    request_url = f"{SCRAPFLY_ENDPOINT}?{params}"
    try:
        with urlopen(request_url, timeout=160) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} en Scrapfly: {body[:300]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Error de red en Scrapfly: {exc.reason}") from exc


def fetch_seller_catalog(seller, scrapfly_key):
    seller_id = extract_seller_id(seller)
    offset = 0
    items = {}
    total = None

    while total is None or offset < total:
        target_url = f"{MELI_SEARCH_ENDPOINT}?seller_id={seller_id}&offset={offset}&limit={PAGE_SIZE}"
        payload = fetch_json_via_scrapfly(target_url, scrapfly_key)
        results = payload.get("results", [])
        paging = payload.get("paging", {})
        total = paging.get("total", 0)
        limit = paging.get("limit") or PAGE_SIZE

        for result in results:
            item_id = str(result.get("id") or "").strip()
            if not item_id:
                continue
            items[item_id] = {
                "seller_name": seller["seller_name"],
                "item_id": item_id,
                "title": (result.get("title") or "").strip(),
                "price": normalize_price(result.get("price")),
                "link": result.get("permalink") or result.get("url") or "",
                "thumbnail": result.get("thumbnail") or "",
                "category": result.get("category_id") or result.get("category") or "",
            }

        if not results:
            break
        offset += limit

    return items


def ensure_state_shape(raw_state):
    state = raw_state if isinstance(raw_state, dict) else {}
    state.setdefault("last_run_at", None)
    state.setdefault("last_run_date", None)
    state.setdefault("items", {})
    if not isinstance(state["items"], dict):
        state["items"] = {}
    return state


def build_report(today, events, errors):
    lines = [
        "# Reporte monitor Mercado Libre Uruguay",
        "",
        f"Fecha de corrida: {today}",
        "",
    ]

    if errors:
        lines.extend(["## Errores", ""])
        for error in errors:
            lines.append(f"- {error}")
        lines.append("")

    sections = [
        ("Nuevas", events["new"], lambda e: f"- {e['seller_name']} / {e['title']} / {format_price(e['price'])} / {e['link']}"),
        ("Bajas", events["removed"], lambda e: f"- {e['seller_name']} / {e['title']} / {format_price(e['price'])} / {e['link']}"),
        (
            "Cambios de precio",
            events["price_changed"],
            lambda e: f"- {e['seller_name']} / {e['title']} / {format_price(e['old_price'])} / {format_price(e['new_price'])} / {e['link']}",
        ),
        (
            "Cambios de título",
            events["title_changed"],
            lambda e: f"- {e['seller_name']} / {e['old_title']} → {e['new_title']} / {format_price(e['price'])} / {e['link']}",
        ),
        (
            "Salidas probables",
            events["salida_probable_media"] + events["salida_probable_alta"],
            lambda e: f"- {e['level']} / {e['seller_name']} / {e['title']} / {format_price(e['price'])} / {e['link']}",
        ),
    ]

    for title, data, formatter in sections:
        lines.extend([f"## {title}", ""])
        if not data:
            lines.append("- Sin novedades")
        else:
            for entry in data:
                lines.append(formatter(entry))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    scrapfly_key = os.getenv("SCRAPFLY_KEY", "").strip()
    if not scrapfly_key:
        raise SystemExit("Falta la variable de entorno SCRAPFLY_KEY")

    sellers = load_json_file(SELLERS_FILE, [])
    if not isinstance(sellers, list):
        raise SystemExit("sellers.json debe contener una lista")

    state = ensure_state_shape(load_json_file(STATE_FILE, {}))
    previous_items = state["items"]
    updated_items = {}

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    events = {
        "new": [],
        "removed": [],
        "price_changed": [],
        "title_changed": [],
        "salida_probable_media": [],
        "salida_probable_alta": [],
    }
    errors = []

    for seller in sellers:
        seller_name = seller.get("seller_name", "").strip()
        if not seller_name:
            logging.error("Seller sin seller_name, se omite")
            continue

        seller_previous = {
            item_id: dict(item)
            for item_id, item in previous_items.items()
            if item.get("seller_name") == seller_name
        }

        try:
            current_items = fetch_seller_catalog(seller, scrapfly_key)
            logging.info("Seller %s procesado con %s items", seller_name, len(current_items))
        except Exception as exc:
            logging.exception("Fallo Scrapfly para seller %s", seller_name)
            errors.append(f"{seller_name}: {exc}")
            updated_items.update(seller_previous)
            continue

        previous_count = len(seller_previous)
        current_count = len(current_items)
        suspicious_incomplete = previous_count > 0 and (
            current_count == 0
            or (current_count < previous_count and current_count <= max(1, previous_count // 5))
        )
        if suspicious_incomplete:
            message = (
                f"{seller_name}: catálogo sospechosamente incompleto "
                f"({current_count} vs {previous_count} previos), se conserva estado previo"
            )
            logging.warning(message)
            errors.append(message)
            updated_items.update(seller_previous)
            continue

        seen_ids = set()

        for item_id, current in current_items.items():
            previous = seller_previous.get(item_id)
            seen_ids.add(item_id)

            record = {
                "seller_name": seller_name,
                "item_id": item_id,
                "title": current["title"],
                "price": current["price"],
                "link": current["link"],
                "thumbnail": current["thumbnail"],
                "category": current["category"],
                "last_seen_date": today,
                "missing_days": 0,
            }

            if previous is None:
                events["new"].append(record.copy())
            else:
                previous_missing_days = int(previous.get("missing_days", 0) or 0)
                if previous_missing_days > 0:
                    logging.info("Item reactivado: %s / %s", seller_name, item_id)
                if previous.get("price") != current["price"]:
                    events["price_changed"].append(
                        {
                            "seller_name": seller_name,
                            "title": current["title"],
                            "old_price": previous.get("price"),
                            "new_price": current["price"],
                            "link": current["link"],
                        }
                    )
                if (previous.get("title") or "") != current["title"]:
                    events["title_changed"].append(
                        {
                            "seller_name": seller_name,
                            "old_title": previous.get("title") or "",
                            "new_title": current["title"],
                            "price": current["price"],
                            "link": current["link"],
                        }
                    )

            updated_items[item_id] = record

        for item_id, previous in seller_previous.items():
            if item_id in seen_ids:
                continue
            missing_days = int(previous.get("missing_days", 0) or 0) + 1
            record = {
                "seller_name": seller_name,
                "item_id": item_id,
                "title": previous.get("title") or "",
                "price": previous.get("price"),
                "link": previous.get("link") or "",
                "thumbnail": previous.get("thumbnail") or "",
                "category": previous.get("category") or "",
                "last_seen_date": previous.get("last_seen_date") or state.get("last_run_date") or today,
                "missing_days": missing_days,
            }
            updated_items[item_id] = record

            if missing_days == 1:
                events["removed"].append(record.copy())
            elif missing_days == 3:
                probable = record.copy()
                probable["level"] = "media"
                events["salida_probable_media"].append(probable)
            elif missing_days == 7:
                probable = record.copy()
                probable["level"] = "alta"
                events["salida_probable_alta"].append(probable)

    state["last_run_at"] = now.isoformat()
    state["last_run_date"] = today
    state["items"] = dict(sorted(updated_items.items(), key=lambda pair: (pair[1].get("seller_name", ""), pair[0])))

    save_json_file(STATE_FILE, state)
    REPORT_FILE.write_text(build_report(today, events, errors), encoding="utf-8")
    logging.info("Corrida finalizada. Estado y reporte actualizados.")


if __name__ == "__main__":
    main()
