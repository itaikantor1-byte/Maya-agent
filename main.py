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

# רשימת מיילים שכבר טופלו (כדי לא לשלוח פעמיים)
processed_emails = set()

def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
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
            if content_type == "text/plain" or content_type == "text/html":
                try:
                    body += part.get_payload(decode=True).decode(errors="ignore")
                except:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(errors="ignore")
        except:
            body = str(msg.get_payload())
    return body[:8000]  # מגביל אורך

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
