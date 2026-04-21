"""
Sends the generated Excel file as an email attachment via Gmail SMTP.

Env vars required (set as GitHub Secrets):
  GMAIL_USER     - the Gmail address used to send (e.g. sender@gmail.com)
  GMAIL_APP_PASS - a Google "App Password" (NOT your normal password)
  EMAIL_TO       - destination address (e.g. recipient@example.com)
"""
import os
import sys
import smtplib
from datetime import datetime
from zoneinfo import ZoneInfo
from email.message import EmailMessage
from pathlib import Path

from generate_report import build_workbook


def main():
    gmail_user = os.environ["GMAIL_USER"]
    gmail_pass = os.environ["GMAIL_APP_PASS"]
    email_to = os.environ["EMAIL_TO"]

    now_uae = datetime.now(ZoneInfo("Asia/Dubai"))
    date_str = now_uae.strftime("%Y-%m-%d")
    file_path = Path(f"Cloud_Services_Update_{date_str}.xlsx")

    build_workbook(str(file_path))
    print(f"Generated: {file_path}")

    msg = EmailMessage()
    msg["Subject"] = f"Daily Cloud Services Update (AWS + OCI) — {now_uae.strftime('%d %b %Y')}"
    msg["From"] = gmail_user
    msg["To"] = email_to
    msg.set_content(
        f"Hi,\n\n"
        f"Attached is today's daily AWS + OCI services & offerings update "
        f"({now_uae.strftime('%A, %d %B %Y')}).\n\n"
        f"The file contains four sheets:\n"
        f"  1. Summary       — counts, sources, and lookback window\n"
        f"  2. Events        — live and upcoming cloud events (re:Invent, re:Inforce, Oracle AI World, etc.)\n"
        f"                     with any announcements in today's feed that reference them\n"
        f"  3. AWS Updates   — live items pulled from AWS What's New and AWS News Blog\n"
        f"  4. OCI Updates   — live items pulled from OCI per-service release notes and OCI blog\n\n"
        f"This is an automated message.\n"
    )

    with open(file_path, "rb") as f:
        data = f.read()
    msg.add_attachment(
        data,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=file_path.name,
    )

    print(f"Sending to {email_to} ...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(gmail_user, gmail_pass)
        smtp.send_message(msg)
    print("Email sent successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
