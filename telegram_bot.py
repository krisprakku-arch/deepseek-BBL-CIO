#!/usr/bin/env python3
import os
import logging
import feedparser
import re
import yfinance as yf
import pandas_datareader.data as web
from datetime import datetime, timedelta, timezone
from openai import OpenAI
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FRED_API_KEY = os.getenv("FRED_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# แหล่งข่าวคุณภาพสูง รวม Investing.com
RSS_FEEDS = {
    "Reuters Business": "http://feeds.reuters.com/reuters/businessNews",
    "CNBC Economy": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "CNBC Markets": "https://www.cnbc.com/id/100011142/device/rss/rss.html",
    "Investing.com (Global)": "https://www.investing.com/rss/news.rss",
    "Investing.com (Economy)": "https://www.investing.com/rss/economy.rss",
    "WSJ Markets (via Google)": "https://news.google.com/rss/search?q=site:wsj.com+markets&hl=en&gl=US&ceid=US:en",
}

def fetch_news(hours=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    articles = []
    for src, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for e in feed.entries:
                pub = None
                if hasattr(e, 'published_parsed') and e.published_parsed:
                    pub = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
                if pub and pub < cutoff:
                    continue
                summary = re.sub('<.*?>', '', e.get('summary', e.get('description', '')))
                summary = ' '.join(summary.split())[:400]
                articles.append({
                    "title": e.get('title', '').strip(),
                    "summary": summary,
                    "source": src,
                    "published": pub.strftime('%Y-%m-%d %H:%M UTC') if pub else 'เวลาล่าสุด',
                })
        except Exception as e:
            logger.error(f"{src} error: {e}")
    seen = set()
    unique = []
    for a in articles:
        key = a['title'][:80].lower()
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique

def get_stock_quote(symbol):
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        price = info.get('regularMarketPrice')
        change = info.get('regularMarketChangePercent')
        if price and change:
            return f"{symbol}: ${price:.2f} ({change:+.2f}%)"
        return None
    except:
        return None

def get_market_summary():
    indices = {"S&P 500": "^GSPC", "NASDAQ": "^IXIC", "Dow Jones": "^DJI"}
    summary = "ดัชนีล่าสุด:\n"
    for name, sym in indices.items():
        q = get_stock_quote(sym)
        if q:
            summary += f"- {name}: {q.split(':')[1]}\n"
    return summary

def get_fed_rate():
    if not FRED_API_KEY:
        return "🔑 ยังไม่มี FRED_API_KEY"
    try:
        df = web.DataReader('DFF', 'fred', start=datetime.now()-timedelta(days=30), api_key=FRED_API_KEY)
        latest = df.iloc[-1][0]
        return f"🏦 อัตราดอกเบี้ยนโยบาย: {latest:.2f}%"
    except:
        return "⚠️ ไม่สามารถดึงอัตราดอกเบี้ยได้"

def get_cpi():
    if not FRED_API_KEY:
        return ""
    try:
        df = web.DataReader('CPIAUCSL', 'fred', start=datetime.now()-timedelta(days=365), api_key=FRED_API_KEY)
        latest = df.iloc[-1][0]
        prev = df.iloc[-2][0]
        change = (latest - prev) / prev * 100
        return f"📊 CPI ล่าสุด: {latest:.1f} (YoY {change:+.2f}%)"
    except:
        return ""

def build_prompt(question, news_articles):
    if not news_articles:
        news_section = "⚠️ ไม่พบข่าวล่าสุด"
    else:
        news_section = ""
        for i, a in enumerate(news_articles[:25], 1):
            news_section += f"{i}. [{a['source']}] {a['title']} ({a['published']})\n   {a['summary'][:300]}\n\n"
    market_data = get_market_summary()
    fed_rate = get_fed_rate()
    cpi = get_cpi()
    prompt = f"""คุณคือนักวิเคราะห์การลงทุน จงตอบโดยอาศัยข้อมูลต่อไปนี้เท่านั้น ต้องใส่ตัวเลขทุกครั้ง

📰 ข่าวล่าสุด:
{news_section}

📊 ข้อมูลตลาด:
{market_data}
{fed_rate}
{cpi}

❓ คำถาม: {question}

รูปแบบคำตอบ:
1. ประเด็นสำคัญ 2-3 ข้อ พร้อมตัวเลขและแหล่งข่าว
2. ผลกระทบต่อตลาด
3. บทสรุปสั้น ๆ

ตอบภาษาไทย:
"""
    return prompt

def ask_deepseek(question, news_articles):
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")
    prompt = build_prompt(question, news_articles)
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1500
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return "ขออภัย ไม่สามารถติดต่อ DeepSeek ได้"

async def start(update, update_context):
    await update.message.reply_text(
        "📈 *บอทการลงทุน (ข่าวจาก Investing.com, Reuters, CNBC)*\n\n"
        "ถามได้เลย เช่น:\n"
        "- สรุปข่าวเศรษฐกิจสหรัฐ\n"
        "- การเคลื่อนไหวของหุ้น AI\n"
        "- อัตราดอกเบี้ยเฟดล่าสุด\n\n"
        "กรุณารอสักครู่...",
        parse_mode="Markdown"
    )

async def handle_message(update, update_context):
    q = update.message.text
    await update.message.reply_text("🔍 กำลังหาข่าวจาก Investing.com และ Reuters...")
    news = fetch_news(24)
    logger.info(f"News count: {len(news)}")
    answer = ask_deepseek(q, news)
    await update.message.reply_text(answer[:4000])

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("ไม่มี TELEGRAM_BOT_TOKEN")
        return
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("บอทเริ่มทำงาน (เพิ่ม Investing.com แล้ว)")
    app.run_polling()

if __name__ == "__main__":
    main()
