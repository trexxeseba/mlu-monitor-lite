import smtplib, os
from email.mime.text import MIMEText

host      = os.environ["SMTP_HOST"]
port      = int(os.environ["SMTP_PORT"])
username  = os.environ["SMTP_USERNAME"]
password  = os.environ["SMTP_PASSWORD"]
to_addr   = os.environ["EMAIL_TO"]
from_addr = os.environ["EMAIL_FROM"]

cuerpo = (
    "MLU Monitor Lite - ERROR en workflow\n"
    "\n"
    "La corrida del monitor fallo.\n"
    "\n"
    "Revisa el detalle en:\n"
    "https://github.com/trexxeseba/mlu-monitor-lite/actions\n"
    "\n"
    "No se actualizaron state.json ni reporte_latest.md.\n"
)

msg = MIMEText(cuerpo, "plain", "utf-8")
msg["Subject"] = "MLU Monitor Lite - ERROR en workflow"
msg["From"]    = from_addr
msg["To"]      = to_addr

with smtplib.SMTP(host, port) as s:
    s.starttls()
    s.login(username, password)
    s.sendmail(from_addr, [to_addr], msg.as_bytes())
print("Email de error enviado.")
