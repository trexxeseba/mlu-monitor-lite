import smtplib, os, json, csv, io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

host      = os.environ["SMTP_HOST"]
port      = int(os.environ["SMTP_PORT"])
username  = os.environ["SMTP_USERNAME"]
password  = os.environ["SMTP_PASSWORD"]
to_addr   = os.environ["EMAIL_TO"]
from_addr = os.environ["EMAIL_FROM"]

MAX_ITEMS_PER_SECTION = 15
BOOTSTRAP_THRESHOLD   = 200   # si hay más de N nuevos, se considera corrida inicial

report_path = Path("reporte_latest.md")
events_path = Path("events.json")

events = {}
try:
    events = json.loads(events_path.read_text(encoding="utf-8"))
except Exception:
    pass

report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else "(sin reporte)"

nuevas      = events.get("new", [])
confirmadas = events.get("removed", [])
pendientes  = events.get("removed_pendiente", [])
precios     = events.get("price_changed", [])
titulos     = events.get("title_changed", [])
salidas     = (events.get("salida_probable_media", []) +
               events.get("salida_probable_alta", []))
errores     = events.get("errors", [])
items_total = events.get("items_total", "?")
fecha       = events.get("run_at", "?")

is_bootstrap = len(nuevas) >= BOOTSTRAP_THRESHOLD


def fmt_price(v):
    if v is None or v == "":
        return "sin precio"
    if isinstance(v, float):
        return f"${v:.2f}"
    return f"${v}"


def section_lines(items, kind="new"):
    lines = []
    for item in items[:MAX_ITEMS_PER_SECTION]:
        seller = item.get("seller_name", "")
        title  = item.get("title", "")
        link   = item.get("link", "")
        price  = fmt_price(item.get("price"))

        if kind == "price":
            old_p = fmt_price(item.get("old_price"))
            new_p = fmt_price(item.get("new_price"))
            lines.append(f"  {seller} | {title} | {old_p} -> {new_p}")
        elif kind == "title":
            old_t = item.get("old_title", "")
            new_t = item.get("new_title", title)
            lines.append(f"  {seller} | {old_t} -> {new_t} | {price}")
        elif kind == "salida":
            level = item.get("level", "?")
            lines.append(f"  [{level.upper()}] {seller} | {title} | {price}")
        else:
            lines.append(f"  {seller} | {title} | {price}")

        if link:
            lines.append(f"    {link}")
    if len(items) > MAX_ITEMS_PER_SECTION:
        lines.append(f"  ... y {len(items) - MAX_ITEMS_PER_SECTION} más (ver adjunto)")
    return lines


# ── Cuerpo del email ──────────────────────────────────────────────────────────
body_lines = [
    "MLU Monitor Lite - Resumen diario",
    "",
    f"Fecha/hora : {fecha}",
    f"Items en seguimiento: {items_total}",
    "",
    "RESUMEN",
    f"  Items nuevos          : {len(nuevas)}" + (" [CORRIDA INICIAL]" if is_bootstrap else ""),
    f"  Bajas confirmadas     : {len(confirmadas)}",
    f"  Bajas pendientes      : {len(pendientes)}",
    f"  Cambios de precio     : {len(precios)}",
    f"  Cambios de titulo     : {len(titulos)}",
    f"  Salidas probables     : {len(salidas)}",
    f"  Errores de sellers    : {len(errores)}",
    "",
]

# Nuevos
body_lines.append("=" * 60)
body_lines.append(f"NUEVOS ({len(nuevas)})")
body_lines.append("=" * 60)
if is_bootstrap:
    body_lines.append("  Corrida inicial / bootstrap.")
    body_lines.append("  El detalle completo esta en el adjunto events_detail.csv")
elif nuevas:
    body_lines.extend(section_lines(nuevas, "new"))
else:
    body_lines.append("  Sin novedades")
body_lines.append("")

# Cambios de precio
body_lines.append("=" * 60)
body_lines.append(f"CAMBIOS DE PRECIO ({len(precios)})")
body_lines.append("=" * 60)
if precios:
    body_lines.extend(section_lines(precios, "price"))
else:
    body_lines.append("  Sin novedades")
body_lines.append("")

# Cambios de titulo
body_lines.append("=" * 60)
body_lines.append(f"CAMBIOS DE TITULO ({len(titulos)})")
body_lines.append("=" * 60)
if titulos:
    body_lines.extend(section_lines(titulos, "title"))
else:
    body_lines.append("  Sin novedades")
body_lines.append("")

# Bajas confirmadas
body_lines.append("=" * 60)
body_lines.append(f"BAJAS CONFIRMADAS ({len(confirmadas)})")
body_lines.append("=" * 60)
if confirmadas:
    body_lines.extend(section_lines(confirmadas, "new"))
else:
    body_lines.append("  Sin novedades")
body_lines.append("")

# Bajas pendientes
body_lines.append("=" * 60)
body_lines.append(f"BAJAS PENDIENTES ({len(pendientes)})")
body_lines.append("=" * 60)
if pendientes:
    body_lines.extend(section_lines(pendientes, "new"))
else:
    body_lines.append("  Sin novedades")
body_lines.append("")

# Salidas probables
body_lines.append("=" * 60)
body_lines.append(f"SALIDAS PROBABLES ({len(salidas)})")
body_lines.append("=" * 60)
if salidas:
    body_lines.extend(section_lines(salidas, "salida"))
else:
    body_lines.append("  Sin novedades")
body_lines.append("")

# Errores
if errores:
    body_lines.append("=" * 60)
    body_lines.append(f"ERRORES DE SELLERS ({len(errores)})")
    body_lines.append("=" * 60)
    for e in errores:
        body_lines.append(f"  {e}")
    body_lines.append("")

body_lines.append("Reporte completo adjunto como reporte_latest.md")

body_text = "\n".join(body_lines)

# ── CSV de detalle completo ───────────────────────────────────────────────────
csv_buf = io.StringIO()
writer = csv.writer(csv_buf)
writer.writerow(["tipo", "seller", "titulo", "precio", "precio_anterior", "titulo_anterior", "nivel", "link"])

for item in nuevas:
    writer.writerow(["nuevo", item.get("seller_name",""), item.get("title",""),
                     item.get("price",""), "", "", "", item.get("link","")])
for item in precios:
    writer.writerow(["cambio_precio", item.get("seller_name",""), item.get("title",""),
                     item.get("new_price",""), item.get("old_price",""), "", "", item.get("link","")])
for item in titulos:
    writer.writerow(["cambio_titulo", item.get("seller_name",""), item.get("new_title",""),
                     item.get("price",""), "", item.get("old_title",""), "", item.get("link","")])
for item in confirmadas:
    writer.writerow(["baja_confirmada", item.get("seller_name",""), item.get("title",""),
                     item.get("price",""), "", "", "", item.get("link","")])
for item in pendientes:
    writer.writerow(["baja_pendiente", item.get("seller_name",""), item.get("title",""),
                     item.get("price",""), "", "", "", item.get("link","")])
for item in salidas:
    writer.writerow(["salida_probable", item.get("seller_name",""), item.get("title",""),
                     item.get("price",""), "", "", item.get("level",""), item.get("link","")])

csv_bytes = csv_buf.getvalue().encode("utf-8")

# ── Armar y enviar el email ───────────────────────────────────────────────────
msg = MIMEMultipart()
msg["Subject"] = "MLU Monitor Lite - resumen diario"
msg["From"]    = from_addr
msg["To"]      = to_addr
msg.attach(MIMEText(body_text, "plain", "utf-8"))

# Adjunto 1: reporte_latest.md
if report_path.exists():
    part = MIMEBase("application", "octet-stream")
    part.set_payload(report_path.read_bytes())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="reporte_latest.md")
    msg.attach(part)

# Adjunto 2: events_detail.csv
part2 = MIMEBase("application", "octet-stream")
part2.set_payload(csv_bytes)
encoders.encode_base64(part2)
part2.add_header("Content-Disposition", "attachment", filename="events_detail.csv")
msg.attach(part2)

with smtplib.SMTP(host, port) as s:
    s.starttls()
    s.login(username, password)
    s.sendmail(from_addr, [to_addr], msg.as_bytes())
print("Email de exito enviado.")
