import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
SELLERS_FILE = BASE_DIR / "sellers.json"
STATE_FILE = BASE_DIR / "state.json"
REPORT_FILE = BASE_DIR / "reporte_latest.md"
SCRAPFLY_ENDPOINT = "https://api.scrapfly.io/scrape"
PAGE_SIZE = 48
MAX_PAGES_PER_SELLER = 3
MAX_SECONDS_PER_SELLER = 90

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


def confirm_item_removed(item_id, scrapfly_key):
    """Hace 1 request liviano (sin render_js) a la URL individual del item.
    Devuelve True si el item está confirmado como dado de baja (HTTP 404).
    Devuelve False si no se puede confirmar (challenge, error de red, etc.).
    """
    url = f"https://www.mercadolibre.com.uy/p/{item_id}"
    params = urlencode({
        "key": scrapfly_key,
        "url": url,
        "country": "uy",
        "proxy_pool": "public_residential_pool",
    })
    try:
        with urlopen(f"{SCRAPFLY_ENDPOINT}?{params}", timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            status = payload.get("result", {}).get("status_code")
            return status == 404
    except Exception:
        return False


def fetch_html_via_scrapfly(url, scrapfly_key):
    params = urlencode(
        {
            "key": scrapfly_key,
            "url": url,
            "country": "uy",
            "proxy_pool": "public_residential_pool",
            "render_js": "true",
            "rendering_wait": "5000",
        }
    )
    request_url = f"{SCRAPFLY_ENDPOINT}?{params}"
    try:
        with urlopen(request_url, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
            result = payload.get("result", {})
            if not result.get("success"):
                err = result.get("error") or {}
                raise RuntimeError(
                    f"Scrapfly error {err.get('code','?')}: {err.get('message','')[:200]}"
                )
            return result.get("content", "")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} en Scrapfly: {body[:300]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Error de red en Scrapfly: {exc.reason}") from exc


def parse_items_from_html(html, seller_name):
    soup = BeautifulSoup(html, "html.parser")
    items = {}
    for li in soup.select("li.ui-search-layout__item"):
        title_tag = li.select_one("a.poly-component__title")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        link = title_tag.get("href", "")

        # item_id: preferir wid= param, luego primer MLU en el link
        wid_match = re.search(r"wid=(MLU\d+)", link)
        id_match = re.search(r"(MLU\d+)", link)
        item_id = (wid_match.group(1) if wid_match else (id_match.group(1) if id_match else "")).strip()
        if not item_id:
            continue

        # price: fracción + centavos opcionales
        price_tag = li.select_one(".andes-money-amount__fraction")
        price = None
        if price_tag:
            frac = price_tag.get_text(strip=True).replace(".", "").replace(",", "")
            cents_tag = li.select_one(".andes-money-amount__cents")
            if cents_tag:
                cents = cents_tag.get_text(strip=True).replace(",", ".")
                frac = f"{frac}.{cents}"
            price = normalize_price(frac)

        # thumbnail
        img = li.select_one("img.poly-component__picture")
        thumbnail = img.get("src", "") if img else ""

        items[item_id] = {
            "seller_name": seller_name,
            "item_id": item_id,
            "title": title,
            "price": price,
            "link": link,
            "thumbnail": thumbnail,
            "category": "",
        }
    return items


def get_total_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.select_one(".ui-search-search-result__quantity-results")
    if tag:
        m = re.search(r"(\d[\d.]*)", tag.get_text().replace(".", ""))
        if m:
            return int(m.group(1).replace(".", ""))
    # fallback: buscar en JSON embebido
    m = re.search(r'"total"\s*:\s*(\d+)', html)
    if m:
        return int(m.group(1))
    return None


def fetch_seller_catalog(seller, scrapfly_key):
    seller_id = extract_seller_id(seller)
    seller_name = seller.get("seller_name", "")
    items = {}
    seller_start = time.monotonic()

    # Primera página — siempre con seller_id en la URL
    first_url = f"https://listado.mercadolibre.com.uy/jm/search?seller_id={seller_id}"
    logging.info("Seller %s: scrapeando página 1 — %s", seller_name, first_url)
    html = fetch_html_via_scrapfly(first_url, scrapfly_key)
    page_items = parse_items_from_html(html, seller_name)
    items.update(page_items)

    total = get_total_from_html(html)
    logging.info("Seller %s: total=%s, pag1=%s items", seller_name, total, len(page_items))

    if total is None or total <= PAGE_SIZE:
        return items

    # Páginas siguientes — SIEMPRE incluir seller_id para no contaminar con resultados ajenos
    offset = PAGE_SIZE + 1
    page_num = 2
    while offset <= total:
        elapsed = time.monotonic() - seller_start
        if page_num > MAX_PAGES_PER_SELLER:
            logging.warning("Seller %s: límite de páginas (%s) alcanzado, cortando con %s items", seller_name, MAX_PAGES_PER_SELLER, len(items))
            break
        if elapsed > MAX_SECONDS_PER_SELLER:
            logging.warning("Seller %s: límite de tiempo (%ss) alcanzado en pág %s, cortando con %s items", seller_name, MAX_SECONDS_PER_SELLER, page_num, len(items))
            break
        # URL con seller_id y offset — evita contaminación cruzada
        page_url = f"https://listado.mercadolibre.com.uy/jm/search?seller_id={seller_id}&_Desde_{offset}_NoIndex_True"
        logging.info("Seller %s: scrapeando página %s — %s", seller_name, page_num, page_url)
        html = fetch_html_via_scrapfly(page_url, scrapfly_key)
        page_items = parse_items_from_html(html, seller_name)
        if not page_items:
            logging.warning("Seller %s: página %s devolvió 0 items, cortando", seller_name, page_num)
            break
        items.update(page_items)
        logging.info("Seller %s: pág %s=%s items, acumulados=%s", seller_name, page_num, len(page_items), len(items))
        offset += PAGE_SIZE
        page_num += 1

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
        lines.append("## Errores")
        for e in errors:
            lines.append(f"- {e}")
        lines.append("")

    lines.append("## Nuevas")
    if events["new"]:
        for item in events["new"]:
            lines.append(
                f"- [{item['title']}]({item['link']}) — {item['seller_name']} — {format_price(item['price'])}"
            )
    else:
        lines.append("- Sin novedades")
    lines.append("")

    lines.append("## Bajas confirmadas")
    if events["removed"]:
        for item in events["removed"]:
            lines.append(
                f"- {item['title']} — {item['seller_name']} — último precio: {format_price(item['price'])}"
            )
    else:
        lines.append("- Sin novedades")
    lines.append("")
    lines.append("## Bajas pendientes de confirmar")
    if events.get("removed_pendiente"):
        for item in events["removed_pendiente"]:
            lines.append(
                f"- {item['title']} — {item['seller_name']} — último precio: {format_price(item['price'])} (no apareció en listado, URL no devuelve 404)"
            )
    else:
        lines.append("- Sin novedades")
    lines.append("")

    lines.append("## Cambios de precio")
    if events["price_changed"]:
        for item in events["price_changed"]:
            lines.append(
                f"- [{item['title']}]({item['link']}) — {item['seller_name']} — "
                f"{format_price(item['old_price'])} → {format_price(item['new_price'])}"
            )
    else:
        lines.append("- Sin novedades")
    lines.append("")

    lines.append("## Cambios de título")
    if events["title_changed"]:
        for item in events["title_changed"]:
            lines.append(
                f"- [{item['new_title']}]({item['link']}) — {item['seller_name']} — "
                f"antes: {item['old_title']}"
            )
    else:
        lines.append("- Sin novedades")
    lines.append("")

    lines.append("## Salidas probables")
    probable = events.get("salida_probable_media", []) + events.get("salida_probable_alta", [])
    if probable:
        for item in probable:
            lines.append(
                f"- {item['title']} — {item['seller_name']} — nivel: {item.get('level','?')} — "
                f"último precio: {format_price(item['price'])}"
            )
    else:
        lines.append("- Sin novedades")
    lines.append("")

    return "\n".join(lines)


def main():
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    scrapfly_key = os.getenv("SCRAPFLY_KEY", "").strip()
    if not scrapfly_key:
        raise SystemExit("Falta la variable de entorno SCRAPFLY_KEY")

    sellers = load_json_file(SELLERS_FILE, [])
    if not isinstance(sellers, list):
        raise SystemExit("sellers.json debe contener una lista")

    state = ensure_state_shape(load_json_file(STATE_FILE, {}))
    previous_items = state.get("items", {})

    events = {
        "new": [],
        "removed": [],
        "removed_pendiente": [],
        "price_changed": [],
        "title_changed": [],
        "salida_probable_media": [],
        "salida_probable_alta": [],
    }
    errors = []
    updated_items = {}
    # Para validation gate: acumular sets de item_ids por seller
    seller_itemsets: dict[str, set] = {}

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

        # Validation gate: detectar contaminación cruzada con sellers ya procesados
        current_ids = set(current_items.keys())
        for prev_seller_name, prev_ids in seller_itemsets.items():
            overlap = current_ids & prev_ids
            overlap_ratio = len(overlap) / max(len(current_ids), 1)
            if len(overlap) >= 5 and overlap_ratio >= 0.3:
                msg = (
                    f"CONTAMINACION: {seller_name} comparte {len(overlap)} items "
                    f"({overlap_ratio:.0%}) con {prev_seller_name} — seller descartado"
                )
                logging.error(msg)
                errors.append(msg)
                updated_items.update(seller_previous)
                current_ids = set()  # no agregar al gate
                break
        else:
            if current_ids:
                seller_itemsets[seller_name] = current_ids
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
            prev_missing = int(previous.get("missing_days", 0) or 0)
            # Confirmar baja via URL individual (sin render_js) antes de incrementar missing_days
            baja_confirmada = confirm_item_removed(item_id, scrapfly_key)
            if baja_confirmada:
                missing_days = prev_missing + 1
                logging.info("Baja confirmada (404): %s / %s", seller_name, item_id)
            else:
                missing_days = prev_missing  # no incrementar si no se confirma
                logging.info("Baja NO confirmada (no 404): %s / %s — missing_days se mantiene en %s", seller_name, item_id, prev_missing)
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
                "baja_confirmada": baja_confirmada,
            }
            updated_items[item_id] = record
            if baja_confirmada and missing_days == 1:
                events["removed"].append(record.copy())
            elif not baja_confirmada and prev_missing == 0:
                events["removed_pendiente"].append(record.copy())
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
    # Determinar si la corrida está contaminada
    contamination_errors = [e for e in errors if "CONTAMINACION" in e]
    run_contaminated = len(contamination_errors) > 0
    if run_contaminated:
        logging.error("Corrida marcada como CONTAMINADA: %s sellers descartados", len(contamination_errors))
    # Guardar eventos para el email
    events_export = {k: list(v) if isinstance(v, list) else v for k, v in events.items()}
    events_export["errors"] = errors
    events_export["run_date"] = today
    events_export["run_at"] = now.isoformat()
    events_export["items_total"] = len(state["items"])
    events_export["run_contaminated"] = run_contaminated
    events_export["contamination_errors"] = contamination_errors
    save_json_file(BASE_DIR / "events.json", events_export)
    logging.info("Corrida finalizada. Estado y reporte actualizados.")


if __name__ == "__main__":
    main()
