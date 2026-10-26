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
import io

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

print("=== התחלת סוכן מאיה ===", flush=True)

GMAIL_USER = os.getenv("GMAIL_USER", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

processed_emails = set()

def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=15)
        print(f"Telegram status: {r.status_code}", flush=True)
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

def extract_pdf_text(pdf_url):
    if not pdfplumber:
        print("pdfplumber לא מותקן", flush=True)
        return None
    try:
        print(f"מוריד PDF: {pdf_url}", flush=True)
        r = requests.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            text_parts = []
            max_pages = min(20, len(pdf.pages))
            for page in pdf.pages[:max_pages]:
                extracted = page.extract_text()
                if extracted:
                    text_parts.append(extracted)
            full_text = "\n".join(text_parts)
            full_text = re.sub(r'\s+', ' ', full_text)
            result = full_text.strip()[:18000]
            print(f"אורך טקסט מ-PDF: {len(result)} (מ-{len(pdf.pages)} עמודים)", flush=True)
            return result
    except Exception as e:
        print(f"שגיאה בחילוץ PDF: {e}", flush=True)
        return None

def get_possible_pdf_urls(report_id: str):
    try:
        rid = int(report_id)
        start = (rid // 1000) * 1000 + 1
        end = start + 999
        folder = f"{start}-{end}"
        base = f"https://mayafiles.tase.co.il/rpdf/{folder}"
        return [
            f"{base}/P{report_id}-00.pdf",
            f"{base}/P{report_id}.pdf",
            f"{base}/{report_id}.pdf",
            f"https://mayafiles.tase.co.il/rpdf/P{report_id}-00.pdf",
        ]
    except:
        return []

def fetch_maya_content(url):
    try:
        print(f"בודק דף: {url}", flush=True)

        report_id = None
        if "/reports/" in url:
            parts = url.replace("?", "/").split("/")
            for p in parts:
                clean = p.split("?")[0]
                if clean.isdigit() and len(clean) >= 6:
                    report_id = clean
                    break

        if report_id:
            possible_urls = get_possible_pdf_urls(report_id)
            for pdf_url in possible_urls:
                print(f"מנסה: {pdf_url}", flush=True)
                try:
                    head = requests.head(pdf_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                    if head.status_code == 200:
                        print("PDF נמצא!", flush=True)
                        return extract_pdf_text(pdf_url)
                except:
                    continue
            print("אף PDF לא נמצא בכתובות הישירות", flush=True)

        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if ".pdf" in href.lower():
                full = href if href.startswith("http") else "https://maya.tase.co.il" + href
                return extract_pdf_text(full)

        text = soup.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        result = "\n".join(lines)[:8000]
        print(f"אין PDF, אורך טקסט: {len(result)}", flush=True)
        return result

    except Exception as e:
        print(f"שגיאה בדף מאיה: {e}", flush=True)
        return None

def analyze_report(subject, body):
    prompt = f"""אתה אנליסט שוק הון ישראלי מנוסה.

נושא הדיווח: {subject}

תוכן הדיווח:
{body}

הנחיות חשובות:
- עסקאות רכישה/מיזוג, הצעות רכש, שינויי שליטה, עסקאות גדולות (מעל עשרות מיליוני ש"ח), או עדכונים מהותיים על נכסים/פרויקטים – נחשבים **מהותיים**.
- דיווחים טכניים קטנים (מימוש אופציות קטן, שינוי מרשם רגיל, הודעות שגרתיות) – לא מהותיים.

אם הדיווח מהותי:
1. סיכום קצר וברור של העיקר
2. למה הוא מהותי
3. השפעה אפשרית על החברה (חיובי/שלילי/נייטרלי + הסבר קצר)

אם לא מהותי – ענה רק: לא מהותי

ענה בעברית, בצורה מסודרת וקריאה."""
    try:
        response = model.generate_content(prompt)
        result = response.text.strip()
        print(f"Gemini תשובה: {result[:600]}", flush=True)
        return result
    except Exception as e:
        print(f"שגיאת Gemini: {e}", flush=True)
        return None

def check_emails():
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        return

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("INBOX")

        status, data = mail.search(None, "ALL")
        if status != "OK":
            mail.logout()
            return

        email_ids = data[0].split()
        print(f"סה\"כ מיילים: {len(email_ids)}", flush=True)

        processed_count = 0
        for e_id in email_ids[-40:]:  # בודק את 40 האחרונים
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
            print(f"\n=== בודק ({processed_count+1}): {subject} ===", flush=True)
            processed_count += 1

            link = extract_maya_link(body)
            content = body
            if link:
                fetched = fetch_maya_content(link)
                if fetched and len(fetched) > 300:
                    content = fetched
                    print("משתמש בתוכן מ-PDF", flush=True)

            analysis = analyze_report(subject, content)

            if analysis and "לא מהותי" not in analysis[:40]:
                msg_text = f"📢 <b>{subject}</b>\n\n{analysis}\n\n⏰ {datetime.now().strftime('%d/%m %H:%M')}"
                send_telegram(msg_text)
                print(">>> נשלח לטלגרם", flush=True)
            else:
                print(">>> לא מהותי - לא נשלח", flush=True)

            processed_emails.add(e_id_str)

        print(f"סיים בדיקה של {processed_count} דיווחים ממאייה", flush=True)
        mail.logout()
    except Exception as e:
        print(f"שגיאה כללית: {e}", flush=True)

print("הסוכן התחיל", flush=True)
send_telegram("✅ הסוכן עלה (גרסה משופרת)")

while True:
    check_emails()
    time.sleep(180)
