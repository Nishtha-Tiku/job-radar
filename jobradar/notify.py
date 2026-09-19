"""Send the digest by email (Gmail SMTP) and append it to a Google Sheet (Apps Script web app)."""
import csv
import datetime as dt
import html
import io
import smtplib
import ssl
from email.message import EmailMessage

import requests

from .models import Job

STATUS_LABEL = {"ok": "live", "unverified": "could not check", "unchecked": "not checked"}


def build_csv(jobs: list[Job]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["#", "Company", "Role", "Location", "Posted", "Match", "Source", "Link check", "Apply link"])
    for i, j in enumerate(jobs, 1):
        w.writerow([i, j.company, j.title, j.location, j.posted, j.score, j.source,
                    STATUS_LABEL.get(j.link_status, j.link_status), j.url])
    return buf.getvalue()


def build_html(jobs: list[Job], summary: str) -> str:
    rows = []
    for i, j in enumerate(jobs, 1):
        rows.append(
            "<tr>"
            f"<td>{i}</td><td><b>{html.escape(j.company)}</b></td><td>{html.escape(j.title)}</td>"
            f"<td>{html.escape(j.location)}</td><td>{html.escape(j.posted)}</td><td>{j.score}</td>"
            f"<td>{html.escape(j.source)}</td><td>{STATUS_LABEL.get(j.link_status, j.link_status)}</td>"
            f"<td><a href=\"{html.escape(j.url, quote=True)}\">Apply</a></td></tr>"
        )
    return (
        "<div style=\"font-family:Arial,sans-serif;font-size:14px\">"
        f"<p>{html.escape(summary)}</p>"
        "<table cellpadding=\"6\" cellspacing=\"0\" border=\"1\" style=\"border-collapse:collapse;border-color:#ddd\">"
        "<tr style=\"background:#0b6e73;color:#fff\"><th>#</th><th>Company</th><th>Role</th><th>Location</th>"
        "<th>Posted</th><th>Match</th><th>Source</th><th>Link</th><th>Apply</th></tr>"
        + "".join(rows) + "</table>"
        "<p style=\"color:#666\">Match = resume-keyword score out of 100. \"could not check\" means the site blocks "
        "automated checks; the link is usually fine.</p></div>"
    )


def send_email(env, jobs: list[Job], summary: str, today: dt.date) -> None:
    address, password = env.get("GMAIL_ADDRESS"), env.get("GMAIL_APP_PASSWORD")
    if not (address and password):
        print("Email: skipped (no GMAIL_ADDRESS / GMAIL_APP_PASSWORD)")
        return
    msg = EmailMessage()
    msg["Subject"] = f"Job Radar {today.strftime('%d %b')}: {len(jobs)} jobs to apply to today"
    msg["From"] = address
    msg["To"] = env.get("EMAIL_TO") or address
    plain = summary + "\n\n" + "\n".join(f"{i}. {j.company} | {j.title} | {j.location} | {j.url}" for i, j in enumerate(jobs, 1))
    msg.set_content(plain)
    msg.add_alternative(build_html(jobs, summary), subtype="html")
    msg.add_attachment(build_csv(jobs).encode("utf-8"), maintype="text", subtype="csv", filename=f"jobs-{today}.csv")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(address, password)
        s.send_message(msg)
    print(f"Email: sent {len(jobs)} jobs to {msg['To']}")


def post_sheet(env, jobs: list[Job], today: dt.date) -> None:
    url, token = env.get("SHEET_WEBHOOK_URL"), env.get("SHEET_TOKEN")
    if not (url and token):
        print("Sheet: skipped (no SHEET_WEBHOOK_URL / SHEET_TOKEN)")
        return
    rows = [[today.isoformat(), j.company, j.title, j.location, j.url, j.source, j.score,
             STATUS_LABEL.get(j.link_status, j.link_status)] for j in jobs]
    r = requests.post(url, json={"token": token, "rows": rows}, timeout=60)
    print(f"Sheet: HTTP {r.status_code} {r.text[:200]}")
