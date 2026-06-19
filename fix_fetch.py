import sys
import os
from datetime import datetime, timezone, timedelta
import feedparser

# แก้ไขฟังก์ชัน fetch_rss_news ให้ใช้ UTC และ debug ออกมา
def fetch_rss_news_fixed(hours_back=6):
    cutoff_utc = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    print(f"🔍 Cutoff UTC: {cutoff_utc.isoformat()}")
    all_articles = []
    RSS_FEEDS = {
        "Reuters Business": "http://feeds.reuters.com/reuters/businessNews",
        "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
        "CNBC Economy": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
        "Investing.com": "https://www.investing.com/rss/news.rss",
    }
    for source_name, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            print(f"📡 {source_name}: {len(feed.entries)} entries")
            for entry in feed.entries:
                # ดึงเวลาที่เผยแพร่ (UTC)
                pub_time_utc = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_time_utc = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    pub_time_utc = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                
                # ถ้าหาเวลาไม่ได้ ให้ใช้เวลาปัจจุบัน (จะได้ไม่ถูกตัดทิ้ง)
                if pub_time_utc is None:
                    pub_time_utc = datetime.now(timezone.utc)
                    print(f"   ⚠️ No time for: {entry.get('title', '')[:50]}")
                
                # ตัดข่าวเก่ากว่า cutoff
                if pub_time_utc < cutoff_utc:
                    continue
                
                all_articles.append({
                    "title": entry.get("title", ""),
                    "description": entry.get("summary", entry.get("description", "")),
                    "source": source_name,
                    "publishedAt": pub_time_utc.isoformat(),
                    "link": entry.get("link", "")
                })
        except Exception as e:
            print(f"❌ {source_name} error: {e}")
    
    # ลบซ้ำ (ใช้ title)
    seen = set()
    unique = []
    for a in all_articles:
        key = a["title"][:100].lower()
        if key not in seen:
            seen.add(key)
            unique.append(a)
    print(f"📰 บทความหลังกรองเวลา: {len(unique)}")
    return unique[:30]

# ทดสอบ
if __name__ == "__main__":
    articles = fetch_rss_news_fixed(6)
    for a in articles[:3]:
        print(f"- {a['title']} ({a['publishedAt']})")
