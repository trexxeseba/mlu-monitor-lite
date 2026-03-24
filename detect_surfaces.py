"""
Detecta si cada seller tiene página pública confiable en MercadoLibre Uruguay.
Usa render_js=true para resolver el challenge de bot-detection y seguir la redirección.
"""
import os, json, time, urllib.request, urllib.parse, re

SCRAPFLY_KEY = os.environ.get("SCRAPFLY_KEY", "")

SELLERS = [
    {"seller_name": "CARSL",                          "seller_id": "6470403"},
    {"seller_name": "WILICARBONERO",                  "seller_id": "30727726"},
    {"seller_name": "TIOPACO",                        "seller_id": "42794274"},
    {"seller_name": "CARLOFOTOGRAFIAS",               "seller_id": "65437681"},
    {"seller_name": "LAVITRINA",                      "seller_id": "65472902"},
    {"seller_name": "ELMUSEITO",                      "seller_id": "74533587"},
    {"seller_name": "DESCONOCIDO_81598742",            "seller_id": "81598742"},
    {"seller_name": "ERNESTO UNION",                  "seller_id": "82819150"},
    {"seller_name": "VENGANZADEREINAANA",              "seller_id": "101941840"},
    {"seller_name": "SYLVIAPOMBOSANSBERRO",            "seller_id": "165896717"},
    {"seller_name": "KAMBA CUA",                      "seller_id": "191098554"},
    {"seller_name": "ELCAZADORVINTAGE",               "seller_id": "224996484"},
    {"seller_name": "GAMI4040741",                    "seller_id": "278811319"},
    {"seller_name": "AMADO LIBROS LIBRERIA EN LINEA", "seller_id": "440298103"},
    {"seller_name": "CAAAD7314725",                   "seller_id": "792978463"},
]

def scrape(url, render_js=True, wait_ms=3000):
    params = {
        "key": SCRAPFLY_KEY,
        "url": url,
        "render_js": "true" if render_js else "false",
        "rendering_wait": str(wait_ms),
        "country": "uy",
        "asp": "false",
    }
    api_url = "https://api.scrapfly.io/scrape?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(api_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        result = data.get("result", {})
        status = result.get("status_code", 0)
        final_url = result.get("url", url)
        content = result.get("content", "")
        return status, final_url, content
    except Exception as e:
        return 0, url, str(e)

def check_seller(seller):
    sid  = seller["seller_id"]
    name = seller["seller_name"]

    # 1. Seguir la redirección de _CustId_ con render_js
    cust_url = f"https://lista.mercadolibre.com.uy/_CustId_{sid}"
    status, final_url, html = scrape(cust_url, render_js=True, wait_ms=3000)
    print(f"  _CustId_: status={status} final={final_url[:90]}")

    # 2. Detectar tipo de superficie por la URL final
    surface_type = "ninguna"
    surface_url  = None

    if "/pagina/" in final_url:
        surface_type = "pagina"
        surface_url  = final_url
    elif "/tienda/" in final_url:
        surface_type = "tienda"
        surface_url  = final_url
    else:
        # Buscar en el HTML si hay un link a /pagina/ o /tienda/
        m = re.search(r'(https://www\.mercadolibre\.com\.uy/(?:pagina|tienda)/[^"\'>\s]+)', html)
        if m:
            surface_url  = m.group(1).split("?")[0].rstrip("/")
            surface_type = "pagina" if "/pagina/" in surface_url else "tienda"
            print(f"  Encontrado en HTML: {surface_url[:80]}")

    # 3. Contar items en la página de la superficie
    item_count = 0
    usable     = False

    if surface_url:
        # Contar MLU IDs en el HTML ya obtenido (si la URL final ya es la superficie)
        items_in_html = set(re.findall(r'MLU\d{6,}', html))
        item_count = len(items_in_html)
        usable = status == 200 and item_count > 0
        print(f"  {surface_type}: items_found={item_count} usable={usable}")
    elif status == 200:
        # La URL no redirigió pero devolvió 200 — puede ser el listado directo
        items_in_html = set(re.findall(r'MLU\d{6,}', html))
        item_count = len(items_in_html)
        if item_count > 0:
            surface_type = "listado_directo"
            surface_url  = final_url
            usable = True
            print(f"  listado_directo: items_found={item_count} usable={usable}")
        else:
            print(f"  Sin items en el HTML (status=200 pero 0 MLU IDs)")
    else:
        print(f"  No se encontró superficie usable")

    time.sleep(3)

    return {
        "seller_name":        name,
        "seller_id":          sid,
        "surface_type":       surface_type,
        "surface_url":        surface_url or "",
        "cust_id_status":     status,
        "cust_id_final_url":  final_url,
        "item_count_sample":  item_count,
        "usable":             usable,
    }

results = []
for seller in SELLERS:
    print(f"\n[{seller['seller_name']}] id={seller['seller_id']}")
    r = check_seller(seller)
    results.append(r)

with open("surface_detection_result.json", "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print("\n\n=== TABLA FINAL ===")
print(f"{'Seller':<35} {'Tipo':<20} {'Usable':<8} {'Items':<6} {'URL'}")
print("-" * 110)
for r in results:
    url_short = (r["surface_url"] or r["cust_id_final_url"])[:55]
    usable_str = "SI" if r["usable"] else "NO"
    print(f"{r['seller_name']:<35} {r['surface_type']:<20} {usable_str:<8} {r['item_count_sample']:<6} {url_short}")
