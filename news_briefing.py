#!/usr/bin/env python3
import os
import json
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

RSS_FEEDS = {
    "Reuters Business": "http://feeds.reuters.com/reuters/businessNews",
    "Reuters Company News": "http://feeds.reuters.com/reuters/companyNews",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "CNBC Economy": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "CNBC Markets": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100011142",
    "Investing.com": "https://www.investing.com/rss/news.rss",
}

def fetch_rss_news(hours_back=6):
    cutoff_utc = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    all_articles = []

    for source_name, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            print(f"✅ {source_name}: {len(feed.entries)} entries")
            for entry in feed.entries:
                # Parse publish time (UTC)
                pub_utc = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_utc = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    pub_utc = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                
                # If no time info, keep the article (assume recent)
                if pub_utc is None:
                    pub_utc = datetime.now(timezone.utc)
                
                if pub_utc < cutoff_utc:
                    continue
                    
                all_articles.append({
                    "title": entry.get("title", ""),
                    "description": entry.get("summary", entry.get("description", "")),
                    "source": source_name,
                    "publishedAt": pub_utc.isoformat(),
                    "link": entry.get("link", "")
                })
        except Exception as e:
            print(f"❌ {source_name}: {e}")
    
    # Deduplicate by title
    seen = set()
    unique = []
    for a in all_articles:
        key = a["title"][:100].lower()
        if key not in seen:
            seen.add(key)
            unique.append(a)
    
    print(f"📰 Total articles after filter: {len(unique)}")
    return unique[:30]

def build_prompt(articles):
    today = datetime.now().strftime("%B %d, %Y")
    news_text = ""
    for art in articles:
        news_text += f"- [{art['source']}] {art['title']} ({art['publishedAt']})\n  {art['description'][:300]}...\n\n"
    
    prompt = f"""คุณคือ Head of Investment Strategy ของสถาบันการเงินระดับโลก จงสร้างรายงานสรุปภาวะเศรษฐกิจและการลงทุนประจำวัน ตามรูปแบบด้านล่าง ใช้ภาษาไทยเท่านั้น

วันที่: {today}

รูปแบบที่ต้องส่งออก:
📊 BBL CIO Morning News: {today}

🔴 Top 10 Global Market Drivers
(ใช้ Emoji นำหน้าตามธีม เรียงตามความสำคัญ)

• [Emoji] [หัวข้อข่าวภาษาไทย]
  [สรุป 2-3 ประโยค: บริบท + ตัวเลขสำคัญ + ทิศทาง (เพิ่มขึ้น/ลดลง/สูงกว่าคาด)]

🎯 5 ประเด็นสำคัญที่ต้องจับตามองวันนี้
• 🕒 [เวลา (ถ้ามี)] 📌 [เหตุการณ์]

⚠️ ข้อกำหนด:
- ทุกข่าวต้องมีตัวเลข (%, YoY, MoM, index, yield, price)
- ห้ามใส่ความคิดเห็น, ห้ามคาดการณ์
- หลีกเลี่ยงข่าวที่ไม่มีตัวเลข

ข่าวดิบ (เฉพาะ 6 ชั่วโมงล่าสุด):
{news_text}
"""
    return prompt

def get_summary(articles):
    if not articles:
        return "⚠️ ไม่มีข่าวการเงินในช่วง 6 ชั่วโมงนี้"
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")
    prompt = build_prompt(articles)
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=3000
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"❌ DeepSeek error: {e}"

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing Telegram credentials")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, data=data, timeout=30)
        return r.status_code == 200
    except:
        return False

def run_briefing():
    print(f"\n[{datetime.now().isoformat()}] เริ่มสรุปข่าว...")
    articles = fetch_rss_news(6)
    if not articles:
        send_telegram("⚠️ ไม่มีข่าวการเงินในช่วง 6 ชั่วโมงนี้ กรุณาลองใหม่ภายหลัง")
        return
    summary = get_summary(articles)
    send_telegram(summary)
    print("✅ เสร็จสิ้น")

if __name__ == "__main__":
    run_briefing()
