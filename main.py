import os
import time
import imaplib
import email
from email.header import decode_header
from google import genai
import requests
from datetime import datetime

# --- הגדרות ---
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

processed_emails = set()

def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("חסרים פרטי טלגרם")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        print(f"Telegram status: {r.status_code}")
        if r.status_code != 200:
            print(r.text)
    except Exception as e:
        print(f"שגיאה בשליחה לטלגרם: {e}")

def decode_mime_words(s):
    if s is None:
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
            content_type = part.get_content_type()
            if content_type in ("text/plain", "text/html"):
                try:
                    body += part.get_payload(decode=True).decode(errors="ignore")
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(errors="ignore")
        except Exception:
            body = str(msg.get_payload())
    return body[:8000]

def analyze_report(subject, body):
    prompt = f"""
אתה אנליסט שוק הון ישראלי מקצועי.

קיבלת דיווח חדש ממערכת מאיה:

נושא הדיווח:
{subject}

תוכן הדיווח:
{body}

תפקידך:
1. להחליט אם הדיווח **מהותי** לחברה שדיווחה.
2. אם הוא מהותי – תן:
   - סיכום קצר וברור של הדיווח
   - למה הוא מהותי
   - איך זה עשוי להשפיע על החברה (חיובי / שלילי / נייטרלי + הסבר)

אם הדיווח לא מהותי (למשל דיווח טכני קטן, מימוש אופציות קטן, שינוי מרשם רגיל וכו') – ענה רק במילה: לא מהותי

ענה בעברית בלבד, בצורה מסודרת וקריאה.
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print(f"שגיאה ב-Gemini: {e}")
        return None

def check_emails():
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("חסרים פרטי Gmail")
        return
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("inbox")

        status, messages = mail.search(None, '(OR FROM "mailtase" FROM "maya" SUBJECT "דיווח")')
        if status != "OK":
            mail.logout()
            return

        email_ids = messages[0].split()
        for e_id in email_ids[-15:]:
            e_id_str = e_id.decode()
            if e_id_str in processed_emails:
                continue

            status, msg_data = mail.fetch(e_id, "(RFC822)")
            if status != "OK":
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            subject = decode_mime_words(msg.get("Subject", ""))
            from_ = decode_mime_words(msg.get("From", ""))

            if "mailtase" not in from_.lower() and "מאיה" not in from_ and "maya" not in from_.lower():
                processed_emails.add(e_id_str)
                continue

            body = get_email_body(msg)
            print(f"בודק דיווח: {subject}")

            analysis = analyze_report(subject, body)

            if analysis and "לא מהותי" not in analysis[:40]:
                message = f"""📢 <b>דיווח מהותי חדש ממאייה</b>

<b>נושא:</b>
{subject}

{analysis}

⏰ {datetime.now().strftime("%d/%m/%Y %H:%M")}"""
                send_telegram(message)
                print("נשלח לטלגרם")
            else:
                print("לא מהותי - לא נשלח")

            processed_emails.add(e_id_str)

        mail.logout()
    except Exception as e:
        print(f"שגיאה כללית: {e}")

print("הסוכן של מאיה התחיל לרוץ...")
send_telegram("✅ הסוכן של מאיה עלה בהצלחה ומתחיל לנטר דיווחים")

while True:
    check_emails()
    time.sleep(180)
