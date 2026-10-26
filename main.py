import os
import time
import imaplib
import email
from email.header import decode_header
import google.generativeai as genai
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import re

print("=== התחלת סוכן מאיה ===", flush=True)

GMAIL_USER = os.getenv("GMAIL_USER", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

print(f"Gmail user: {GMAIL_USER}", flush=True)
print(f"Password length: {len(GMAIL_APP_PASSWORD)}", flush=True)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

processed_emails = set()

def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}", flush=True)

def decode_mime_words(s):
    if not s:
        return ""
    decoded = decode_header(s)
    result = ""
    for part, encoding in decoded:
        if isinstance(part, bytes):
            result += part.decode(encoding or "utf-8", errors="ignore")
        else:
            result += part
    return result

def get_email_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body += payload.decode(errors="ignore")
                except:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(errors="ignore")
        except:
            pass
    return body

def extract_maya_link(body):
    for link in re.findall(r'https?://[^\s<>"\']+', body):
        if "maya.tase.co.il" in link or "tase.co.il" in link:
            return link.rstrip(").,;]")
    return None

def fetch_maya_report(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return "\n".join(lines)[:10000]
    except Exception as e:
        print(f"Fetch error: {e}", flush=True)
        return None

def analyze_report(subject, body):
    prompt = f"""אתה אנליסט שוק הון ישראלי.
נושא: {subject}
תוכן: {body}

אם הדיווח מהותי – תן סיכום, למה מהותי והשפעה אפשרית.
אם לא מהותי – ענה רק: לא מהותי
ענה בעברית."""
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Gemini error: {e}", flush=True)
        return None

def check_emails():
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("חסרים פרטי Gmail", flush=True)
        return

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("INBOX")

        status, data = mail.search(None, "ALL")
        if status != "OK":
            print("Search failed", flush=True)
            mail.logout()
            return

        email_ids = data[0].split()
        print(f"Total emails in inbox: {len(email_ids)}", flush=True)

        # רק 30 האחרונים
        for e_id in email_ids[-30:]:
            e_id_str = e_id.decode()
            if e_id_str in processed_emails:
                continue

            status, msg_data = mail.fetch(e_id, "(RFC822)")
            if status != "OK":
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            subject = decode_mime_words(msg.get("Subject", ""))
            from_ = decode_mime_words(msg.get("From", "")).lower()

            if "mailtase" not in from_ and "maya" not in from_ and "מאיה" not in from_:
                processed_emails.add(e_id_str)
                continue

            body = get_email_body(msg)
            print(f"בודק: {subject}", flush=True)

            link = extract_maya_link(body)
            content = body
            if link:
                fetched = fetch_maya_report(link)
                if fetched and len(fetched) > 300:
                    content = fetched

            analysis = analyze_report(subject, content)
            if analysis and "לא מהותי" not in analysis[:25]:
                send_telegram(f"📢 <b>{subject}</b>\n\n{analysis}\n\n⏰ {datetime.now().strftime('%d/%m %H:%M')}")
                print("נשלח", flush=True)
            else:
                print("לא מהותי", flush=True)

            processed_emails.add(e_id_str)

        mail.logout()
    except Exception as e:
        print(f"IMAP Error: {e}", flush=True)

print("הסוכן התחיל", flush=True)
send_telegram("✅ הסוכן עלה")

while True:
    check_emails()
    time.sleep(180)
