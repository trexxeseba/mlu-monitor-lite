
import json, urllib.request, urllib.parse, time, os, sys
from bs4 import BeautifulSoup

KEY = os.environ.get("SCRAPFLY_KEY", "")
ENDPOINT = "https://api.scrapfly.io/scrape"

ITEMS = [
    ("MLU1017803132", "Peter Pan Anotado", "https://www.mercadolibre.com.uy/peter-pan-anotado-edicion-del-centenario-p-dura/p/MLU21365285"),
    ("MLU1019984920", "Elf Bronzer",       "https://www.mercadolibre.com.uy/elf-camo-liquid-bronzer-contour-bronzer-liquido-tono-del-maquillaje-naranja-suave/p/MLU1019984920"),
    ("MLU1031372620", "Elmer Search",      "https://www.mercadolibre.com.uy/elmer-search-and-find-de-david-mckee-editorial-walker-books-en-ingles/p/MLU1031372620"),
    ("MLU1102481936", "Cinta caballos",    "https://www.mercadolibre.com.uy/horse-search-height-measuring-tape/p/MLU2064941862"),
    ("MLU738310946",  "Rubor Maybelline",  "https://www.mercadolibre.com.uy/rubor-maybelline-sunkisser-tono-downtown-rush-tono-del-maquillaje-naranja-suave/MLU738310946"),
]

def scrape(url, render_js=False, asp=False, wait=0):
    params = {"key": KEY, "url": url, "country": "uy", "proxy_pool": "public_residential_pool"}
    if render_js:
        params["render_js"] = "true"
    if wait:
        params["rendering_wait"] = str(wait)
    if asp:
        params["asp"] = "true"
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{ENDPOINT}?{qs}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

def extract(html):
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one("h1.ui-pdp-title") or soup.select_one("h1")
    price = soup.select_one(".andes-money-amount__fraction")
    img = soup.select_one("img.ui-pdp-image") or soup.select_one("figure img")
    avail = soup.select_one(".ui-pdp-buybox__quantity") or soup.select_one("[class*=stock]")
    return {
        "title": title.get_text(strip=True)[:60] if title else None,
        "price": price.get_text(strip=True) if price else None,
        "img": bool(img),
        "avail": avail.get_text(strip=True)[:40] if avail else None,
    }

results = []
for item_id, name, url in ITEMS:
    print(f"\n=== {item_id} | {name} ===", flush=True)
    row = {"item_id": item_id, "name": name, "url": url}

    # Test 1: sin render_js
    d = scrape(url, render_js=False, asp=False)
    r1 = d.get("result", {})
    html1 = r1.get("content", "")
    ex1 = extract(html1)
    row["t1_status"] = r1.get("status_code","?")
    row["t1_html_len"] = len(html1)
    row["t1_title"] = ex1.get("title")
    row["t1_price"] = ex1.get("price")
    row["t1_img"] = ex1.get("img")
    print(f"  [1] sin render_js: HTTP {row['t1_status']}, {row['t1_html_len']}b | title={row['t1_title']} price={row['t1_price']}", flush=True)

    time.sleep(2)

    # Test 2: asp=true sin render_js
    d2 = scrape(url, render_js=False, asp=True)
    r2 = d2.get("result", {})
    html2 = r2.get("content", "")
    ex2 = extract(html2)
    row["t2_status"] = r2.get("status_code","?")
    row["t2_html_len"] = len(html2)
    row["t2_title"] = ex2.get("title")
    row["t2_price"] = ex2.get("price")
    print(f"  [2] asp=true: HTTP {row['t2_status']}, {row['t2_html_len']}b | title={row['t2_title']} price={row['t2_price']}", flush=True)

    time.sleep(2)

    # Test 3: render_js + wait 5000
    d3 = scrape(url, render_js=True, asp=False, wait=5000)
    r3 = d3.get("result", {})
    html3 = r3.get("content", "")
    ex3 = extract(html3)
    row["t3_status"] = r3.get("status_code","?")
    row["t3_html_len"] = len(html3)
    row["t3_title"] = ex3.get("title")
    row["t3_price"] = ex3.get("price")
    row["t3_img"] = ex3.get("img")
    row["t3_avail"] = ex3.get("avail")
    print(f"  [3] render_js+wait5s: HTTP {row['t3_status']}, {row['t3_html_len']}b | title={row['t3_title']} price={row['t3_price']} avail={row['t3_avail']}", flush=True)

    results.append(row)
    time.sleep(3)

with open("test_items_result.json", "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("\n=== DONE ===")
