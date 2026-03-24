"""
Detecta si cada seller tiene página pública confiable en MercadoLibre Uruguay:
- /pagina/{slug}
- /tienda/{slug}
Usa Scrapfly sin render_js para verificar redirección y contenido.
"""
import os, json, time, urllib.request, urllib.parse

SCRAPFLY_KEY = os.environ.get("SCRAPFLY_KEY", "")

SELLERS = [
    {"seller_name": "CARSL",                        "seller_id": "6470403"},
    {"seller_name": "WILICARBONERO",                "seller_id": "30727726"},
    {"seller_name": "TIOPACO",                      "seller_id": "42794274"},
    {"seller_name": "CARLOFOTOGRAFIAS",             "seller_id": "65437681"},
    {"seller_name": "LAVITRINA",                    "seller_id": "65472902"},
    {"seller_name": "ELMUSEITO",                    "seller_id": "74533587"},
    {"seller_name": "DESCONOCIDO_81598742",         "seller_id": "81598742"},
    {"seller_name": "ERNESTO UNION",                "seller_id": "82819150"},
    {"seller_name": "VENGANZADEREINAANA",           "seller_id": "101941840"},
    {"seller_name": "SYLVIAPOMBOSANSBERRO",         "seller_id": "165896717"},
    {"seller_name": "KAMBA CUA",                    "seller_id": "191098554"},
    {"seller_name": "ELCAZADORVINTAGE",             "seller_id": "224996484"},
    {"seller_name": "GAMI4040741",                  "seller_id": "278811319"},
    {"seller_name": "AMADO LIBROS LIBRERIA EN LINEA", "seller_id": "440298103"},
    {"seller_name": "CAAAD7314725",                 "seller_id": "792978463"},
]

def scrape_url(url, render_js=False):
    """Hace un request via Scrapfly y devuelve (status_code, final_url, html_snippet)"""
    params = {
        "key": SCRAPFLY_KEY,
        "url": url,
        "render_js": "true" if render_js else "false",
        "country": "uy",
        "asp": "false",
    }
    api_url = "https://api.scrapfly.io/scrape?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(api_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        result = data.get("result", {})
        status = result.get("status_code", 0)
        final_url = result.get("url", url)
        content = result.get("content", "")
        return status, final_url, content[:3000]
    except Exception as e:
        return 0, url, str(e)

def check_seller(seller):
    sid = seller["seller_id"]
    name = seller["seller_name"]
    results = {}

    # 1. URL _CustId_ (redirect a /pagina/ o /tienda/)
    cust_url = f"https://lista.mercadolibre.com.uy/_CustId_{sid}"
    status, final_url, html = scrape_url(cust_url)
    results["cust_id"] = {"url": cust_url, "status": status, "final_url": final_url}
    print(f"  _CustId_: status={status} final={final_url[:80]}")

    # 2. Detectar si redirigió a /pagina/ o /tienda/
    surface_type = "ninguna"
    surface_url = None
    if "/pagina/" in final_url:
        surface_type = "pagina"
        surface_url = final_url
    elif "/tienda/" in final_url:
        surface_type = "tienda"
        surface_url = final_url
    elif status == 200 and ("pagina" in html or "tienda" in html):
        # Buscar en el HTML
        import re
        m = re.search(r'(https://www\.mercadolibre\.com\.uy/(?:pagina|tienda)/[^"\'>\s]+)', html)
        if m:
            surface_url = m.group(1)
            surface_type = "pagina" if "/pagina/" in surface_url else "tienda"

    # 3. Si encontramos una superficie, verificar que tiene items
    usable = False
    item_count = 0
    if surface_url:
        s2, fu2, html2 = scrape_url(surface_url)
        print(f"  {surface_type}: status={s2} url={surface_url[:80]}")
        # Contar items en el HTML
        import re
        items_found = re.findall(r'MLU\d{6,}', html2)
        item_count = len(set(items_found))
        usable = s2 == 200 and item_count > 0
        print(f"  items_found={item_count} usable={usable}")
    else:
        print(f"  No se encontró /pagina/ ni /tienda/")

    time.sleep(2)  # pausa entre sellers

    return {
        "seller_name": name,
        "seller_id": sid,
        "surface_type": surface_type,
        "surface_url": surface_url or "",
        "cust_id_status": results["cust_id"]["status"],
        "cust_id_final_url": results["cust_id"]["final_url"],
        "item_count_sample": item_count,
        "usable": usable,
    }

results = []
for seller in SELLERS:
    print(f"\n[{seller['seller_name']}] id={seller['seller_id']}")
    r = check_seller(seller)
    results.append(r)

with open("surface_detection_result.json", "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print("\n\n=== TABLA FINAL ===")
print(f"{'Seller':<35} {'Tipo':<8} {'Usable':<8} {'Items':<6} {'URL'}")
print("-" * 100)
for r in results:
    url_short = r["surface_url"][:50] if r["surface_url"] else r["cust_id_final_url"][:50]
    print(f"{r['seller_name']:<35} {r['surface_type']:<8} {'SI' if r['usable'] else 'NO':<8} {r['item_count_sample']:<6} {url_short}")
