import smtplib, os, json
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

report_path = Path("reporte_latest.md")
report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else "(sin reporte)"


def count_section(text, header):
    lines = []
    in_section = False
    for line in text.splitlines():
        if line.strip() == "## " + header:
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            if line.strip().startswith("- ") and "Sin novedades" not in line:
                lines.append(line)
    return lines


nuevas      = count_section(report_text, "Nuevas")
confirmadas = count_section(report_text, "Bajas confirmadas")
pendientes  = count_section(report_text, "Bajas pendientes de confirmar")
precios     = count_section(report_text, "Cambios de precio")
salidas     = count_section(report_text, "Salidas probables")

state = {}
try:
    state = json.loads(Path("state.json").read_text())
except Exception:
    pass
items_total = len(state.get("items", {}))
fecha = state.get("last_run_at", "?")

resumen = (
    "MLU Monitor Lite - Resumen diario\n"
    "\n"
    f"Fecha/hora: {fecha}\n"
    "Sellers configurados: 15\n"
    f"Items en seguimiento: {items_total}\n"
    "\n"
    "Novedades:\n"
    f"  Items nuevos:            {len(nuevas)}\n"
    f"  Bajas confirmadas:       {len(confirmadas)}\n"
    f"  Bajas pendientes:        {len(pendientes)}\n"
    f"  Cambios de precio:       {len(precios)}\n"
    f"  Salidas probables:       {len(salidas)}\n"
    "\n"
    "Reporte completo adjunto.\n"
)

msg = MIMEMultipart()
msg["Subject"] = "MLU Monitor Lite - resumen diario"
msg["From"]    = from_addr
msg["To"]      = to_addr
msg.attach(MIMEText(resumen, "plain", "utf-8"))

if report_path.exists():
    part = MIMEBase("application", "octet-stream")
    part.set_payload(report_path.read_bytes())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="reporte_latest.md")
    msg.attach(part)

with smtplib.SMTP(host, port) as s:
    s.starttls()
    s.login(username, password)
    s.sendmail(from_addr, [to_addr], msg.as_bytes())
print("Email de exito enviado.")
