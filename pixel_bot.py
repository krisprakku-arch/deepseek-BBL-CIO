import os
import logging
import json
import feedparser
import yfinance as yf
import re
import asyncio
import time
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Cache (force refresh, but background updater will keep it fresh) ----------
news_cache = {"data": [], "expires": 0}
market_cache = {"data": "", "expires": 0}
CACHE_TTL = 0  # no cache on user request, but background updater will preload

def get_cached_news():
    if time.time() < news_cache["expires"]:
        return news_cache["data"]
    return None

def set_cached_news(data, ttl=60):  # cache สำหรับ background updater
    news_cache["data"] = data
    news_cache["expires"] = time.time() + ttl

def get_cached_market():
    if time.time() < market_cache["expires"]:
        return market_cache["data"]
    return None

def set_cached_market(data, ttl=60):
    market_cache["data"] = data
    market_cache["expires"] = time.time() + ttl

# ---------- Background updater ----------
async def background_data_refresh():
    while True:
        try:
            logger.info("Background refresh: fetching news and market data...")
            # ใช้ sync function เรียกผ่าน thread
            news = await asyncio.to_thread(fetch_recent_news_sync, hours=6, use_cache=False)
            market = await asyncio.to_thread(get_market_summary_sync, use_cache=False)
            set_cached_news(news, ttl=120)   # cache สำหรับผู้ใช้ (2 นาที)
            set_cached_market(market, ttl=120)
            logger.info(f"Background refresh done. News: {len(news)} items, Market: {len(market)} chars")
        except Exception as e:
            logger.error(f"Background refresh error: {e}")
        await asyncio.sleep(60)  # ทุก 1 นาที

# ---------- Knowledge ----------
INVESTMENT_KNOWLEDGE = """
MPT, Value Investing, DCA, Risk Mgmt (stop loss 7-10%), Sharpe Ratio >1, RSI>70 overbought, <30 oversold,
Loss aversion, Herding, Confirmation bias, Asset Allocation (age), Emergency fund, REITs, Dividend stocks, Global diversification.
"""

# ---------- Game State ----------
DATA_FILE = "game_data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user_state(user_id):
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "floor": 1,
            "team": [
                {"name": "BP-006", "role": "Dev", "progress": 40},
                {"name": "BP-005", "role": "Analyst", "progress": 20},
                {"name": "BP-007", "role": "Operator", "progress": 60}
            ],
            "tasks": [],
            "dossiers": [],
            "credits": 100,
            "next_task_id": 1
        }
        save_data(data)
    return data[uid]

def save_user_state(user_id, state):
    data = load_data()
    data[str(user_id)] = state
    save_data(data)

# ---------- Tasks (unchanged) ----------
def add_task(user_id, title, assigned_to):
    state = get_user_state(user_id)
    task_id = state.get("next_task_id", 1)
    new_task = {
        "id": task_id,
        "title": title,
        "assigned_to": assigned_to,
        "status": "pending",
        "created_at": datetime.now().isoformat()
    }
    state["tasks"].append(new_task)
    state["next_task_id"] = task_id + 1
    save_user_state(user_id, state)
    return new_task

def update_task_status(user_id, task_id, new_status):
    state = get_user_state(user_id)
    for task in state["tasks"]:
        if task["id"] == task_id:
            task["status"] = new_status
            save_user_state(user_id, state)
            return True
    return False

def get_tasks_by_status(user_id, status=None):
    state = get_user_state(user_id)
    if status:
        return [t for t in state["tasks"] if t["status"] == status]
    return state["tasks"]

def format_task_list(tasks, title):
    if not tasks:
        return f"{title}\nไม่มีภารกิจ"
    lines = [title]
    for t in tasks:
        emoji = {"pending":"⏳","in_progress":"🔄","done":"✅","blocked":"🔒","overload":"⚠️"}.get(t["status"],"❓")
        lines.append(f"{emoji} #{t['id']} {t['title']} -> {t['assigned_to']} ({t['status']})")
    return "\n".join(lines)

# ---------- News & Market with optional cache bypass ----------
RSS_FEEDS = {
    "Google News (Economy)": "https://news.google.com/rss/search?q=economy+interest+rates+inflation&hl=en&gl=US&ceid=US:en",
    "Google News (Markets)": "https://news.google.com/rss/search?q=stock+market+earnings+fed&hl=en&gl=US&ceid=US:en",
    "Google News (Commodities)": "https://news.google.com/rss/search?q=oil+gold+commodities&hl=en&gl=US&ceid=US:en"
}

def fetch_recent_news_sync(hours=6, use_cache=True):
    if use_cache:
        cached = get_cached_news()
        if cached:
            return cached
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
                summary = ' '.join(summary.split())[:300]
                articles.append({
                    "title": e.get('title', '').strip(),
                    "summary": summary,
                    "source": src,
                    "published": pub.strftime('%Y-%m-%d %H:%M UTC') if pub else 'ล่าสุด'
                })
        except Exception as e:
            logger.error(f"RSS {src}: {e}")
    seen = set()
    unique = []
    for a in articles:
        key = a['title'][:80].lower()
        if key not in seen:
            seen.add(key)
            unique.append(a)
    if use_cache:
        set_cached_news(unique[:15], ttl=120)
    return unique[:15]

def get_market_summary_sync(use_cache=True):
    if use_cache:
        cached = get_cached_market()
        if cached:
            return cached
    indices = {"S&P500": "^GSPC", "NASDAQ": "^IXIC", "Dow Jones": "^DJI"}
    lines = [f"📅 อัปเดต {datetime.now().strftime('%H:%M:%S')} UTC"]
    for name, sym in indices.items():
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="2d")
            if not hist.empty:
                price = hist['Close'].iloc[-1]
                prev = hist['Close'].iloc[-2] if len(hist) > 1 else price
                change = (price - prev) / prev * 100
                lines.append(f"{name}: {price:.2f} ({change:+.2f}%)")
        except Exception as e:
            lines.append(f"{name}: N/A")
    result = "\n".join(lines)
    if use_cache:
        set_cached_market(result, ttl=120)
    return result

def filter_news_by_keywords(question, articles, top_k=3):
    keywords = set(re.findall(r'\w+', question.lower()))
    stopwords = {'จะ','และ','หรือ','ใน','ของ','ที่','มี','ได้','ไม่','การ','เป็น','ให้','ว่า','ซึ่ง','เมื่อ','เรา','คุณ','ผม','ค่ะ','ครับ'}
    keywords = [kw for kw in keywords if kw not in stopwords and len(kw) > 1]
    scored = []
    for a in articles:
        text = (a['title'] + ' ' + a['summary']).lower()
        score = sum(1 for kw in keywords if kw in text)
        scored.append((score, a))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored[:top_k]]

# ---------- NPC Prompts (detailed) ----------
NPC_SYSTEM_PROMPTS = {
    "macro": f"คุณคือ Dr. Macro นักเศรษฐศาสตร์ ตอบละเอียด 5-6 ประโยค ใช้ตัวเลขเศรษฐกิจ แหล่งที่มา\nความรู้: {INVESTMENT_KNOWLEDGE}",
    "portfolio": f"คุณคือ Ms. Portfolio จัดพอร์ต ตอบละเอียด 5-6 ประโยค พร้อมตัวอย่างตัวเลข\nความรู้: {INVESTMENT_KNOWLEDGE}",
    "hedge": f"คุณคือ Mr. Hedge ความเสี่ยง ตอบละเอียด 5-6 ประโยค เน้น stop loss, VaR, hedging\nความรู้: {INVESTMENT_KNOWLEDGE}",
    "tech": f"คุณคือ Candle Master เทคนิคอล ตอบละเอียด 5-6 ประโยค ใช้ RSI, MACD, support/resistance\nความรู้: {INVESTMENT_KNOWLEDGE}",
    "alt": f"คุณคือ Miss Gold & Crypto วิเคราะห์ทองคำ,BTC,REITs ตอบละเอียด 5-6 ประโยค\nความรู้: {INVESTMENT_KNOWLEDGE}",
    "zen": f"คุณคือ Zen Investor จิตวิทยา ตอบละเอียด 5-6 ประโยค ใช้แนวคิดของ Buffett, Munger\nความรู้: {INVESTMENT_KNOWLEDGE}"
}

async def ask_deepseek_async(question, npc_code, news_articles, market_data, history=[]):
    system_prompt = NPC_SYSTEM_PROMPTS.get(npc_code, f"ผู้เชี่ยวชาญ\n{INVESTMENT_KNOWLEDGE}")
    relevant_news = filter_news_by_keywords(question, news_articles, top_k=3)
    news_text = ""
    for a in relevant_news:
        news_text += f"🔹 {a['title']} ({a['source']}, {a['published']})\n   {a['summary'][:200]}...\n\n"
    if not news_text:
        news_text = "ไม่พบข่าวที่เกี่ยวข้องโดยตรง"
    user_content = f"""📊 ข้อมูลตลาดล่าสุด:
{market_data}

📰 ข่าวที่เกี่ยวข้อง:
{news_text}

❓ คำถาม: {question}

💬 โปรดตอบอย่างละเอียด 5-6 ประโยค แบบมืออาชีพ ภาษาไทย มีตัวเลขและอ้างอิงแหล่งที่มา:
"""
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": user_content})
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.7,
                max_tokens=600
            ),
            timeout=25.0
        )
        return resp.choices[0].message.content
    except asyncio.TimeoutError:
        return "ขออภัย การวิเคราะห์ใช้เวลานานเกินไป (25 วินาที) กรุณาถามใหม่"
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return f"เกิดข้อผิดพลาด: {type(e).__name__}"

async def ask_all_team_async(question, news_articles, market_data):
    system_prompt = """คุณคือหัวหน้าทีมนักวิเคราะห์ 6 คน จงตอบคำถามโดยให้แต่ละคนแสดงความเห็น 2-3 ประโยค:
📈 Dr. Macro (เศรษฐกิจ)
🧠 Ms. Portfolio (จัดพอร์ต)
⚖️ Mr. Hedge (ความเสี่ยง)
📊 Candle Master (เทคนิคอล)
💎 Miss Gold & Crypto (สินทรัพย์ทางเลือก)
🧘 Zen Investor (จิตวิทยา)
แล้วสรุป 2-3 ประโยค"""
    relevant_news = filter_news_by_keywords(question, news_articles, top_k=4)
    news_text = "\n".join([f"- {a['title']} ({a['source']}, {a['published']})" for a in relevant_news]) or "ไม่มีข่าว"
    user_content = f"""📈 ตลาดล่าสุด:
{market_data}

📰 ข่าว:
{news_text}

คำถาม: {question}

ตอบตามรูปแบบ ใช้ภาษาไทย กระชับ:
"""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.7,
                max_tokens=1000
            ),
            timeout=30.0
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"ทีมไม่สามารถประชุมได้: {type(e).__name__}"

# ---------- Menus ----------
def main_menu():
    keyboard = [
        [InlineKeyboardButton("📋 COMMAND", callback_data="cmd")],
        [InlineKeyboardButton("👥 CREW3", callback_data="crew"), InlineKeyboardButton("📌 TASKS3", callback_data="tasks")],
        [InlineKeyboardButton("⚠️ OVERLOAD", callback_data="overload"), InlineKeyboardButton("🔒 BLOCKED", callback_data="blocked")],
        [InlineKeyboardButton("➕ ADD TASK", callback_data="add_task"), InlineKeyboardButton("🔄 UPDATE TASK", callback_data="update_task")],
        [InlineKeyboardButton("🗂️ ALL DOSSIERS", callback_data="dossiers"), InlineKeyboardButton("🔁 REFRESH", callback_data="refresh")],
        [InlineKeyboardButton("🏢 FLOOR", callback_data="floor"), InlineKeyboardButton("👥 TEAM", callback_data="team")],
        [InlineKeyboardButton("⬅️ BACK TO CITY", callback_data="city")],
        [InlineKeyboardButton("📈 ASK TEAM", callback_data="ask_team")]
    ]
    return InlineKeyboardMarkup(keyboard)

def npc_menu():
    keyboard = [
        [InlineKeyboardButton("📈 Dr. Macro", callback_data="npc_macro")],
        [InlineKeyboardButton("🧠 Ms. Portfolio", callback_data="npc_portfolio")],
        [InlineKeyboardButton("⚖️ Mr. Hedge", callback_data="npc_hedge")],
        [InlineKeyboardButton("📊 Candle Master", callback_data="npc_tech")],
        [InlineKeyboardButton("💎 Miss Gold & Crypto", callback_data="npc_alt")],
        [InlineKeyboardButton("🧘 Zen Investor", callback_data="npc_zen")],
        [InlineKeyboardButton("👥 ASK ALL TEAM", callback_data="team_all")],
        [InlineKeyboardButton("🔙 Back", callback_data="refresh")]
    ]
    return InlineKeyboardMarkup(keyboard)

def npc_name(code):
    return {"macro":"Dr. Macro","portfolio":"Ms. Portfolio","hedge":"Mr. Hedge",
            "tech":"Candle Master","alt":"Miss Gold & Crypto","zen":"Zen Investor"}.get(code,"NPC")

def task_action_menu(task_id):
    keyboard = [
        [InlineKeyboardButton("⏳ Pending", callback_data=f"task_status_{task_id}_pending"),
         InlineKeyboardButton("🔄 In Progress", callback_data=f"task_status_{task_id}_in_progress")],
        [InlineKeyboardButton("✅ Done", callback_data=f"task_status_{task_id}_done"),
         InlineKeyboardButton("🔒 Blocked", callback_data=f"task_status_{task_id}_blocked"),
         InlineKeyboardButton("⚠️ Overload", callback_data=f"task_status_{task_id}_overload")],
        [InlineKeyboardButton("🔙 Back", callback_data="tasks")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------- Dossier ----------
def get_dossiers(user_id, npc_filter=None, keyword=None):
    state = get_user_state(user_id)
    dossiers = sorted(state.get("dossiers", []), key=lambda x: x.get("timestamp",""), reverse=True)
    if npc_filter and npc_filter != "all":
        dossiers = [d for d in dossiers if d.get("npc") == npc_filter]
    if keyword:
        kw = keyword.lower()
        dossiers = [d for d in dossiers if kw in d.get("question","").lower() or kw in d.get("answer","").lower()]
    return dossiers

def format_dossier_entry(entry, idx):
    ts = entry.get("timestamp","")[:16].replace("T"," ")
    npc_display = npc_name(entry.get("npc",""))
    q = entry.get("question","")[:80]
    return f"{idx}. [{ts}] *{npc_display}*\n📌 {q}\n"

async def show_dossier_page(update, user_id, page, npc_filter="all", keyword=None):
    dossiers = get_dossiers(user_id, npc_filter, keyword)
    if not dossiers:
        await update.callback_query.edit_message_text("🗂️ ไม่มีรายการ", reply_markup=main_menu())
        return
    per_page = 5
    total = (len(dossiers)+per_page-1)//per_page
    start = page*per_page
    end = start+per_page
    header = f"🗂️ *Dossier* ({npc_filter if npc_filter!='all' else 'ทั้งหมด'}) หน้า {page+1}/{total}\n\n"
    body = "".join(format_dossier_entry(d, i+1) for i,d in enumerate(dossiers[start:end]))
    keyboard = []
    nav = []
    if page>0: nav.append(InlineKeyboardButton("◀️", callback_data=f"dossier_page_{page-1}"))
    if page<total-1: nav.append(InlineKeyboardButton("▶️", callback_data=f"dossier_page_{page+1}"))
    if nav: keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 กลับ", callback_data="refresh")])
    await update.callback_query.edit_message_text(header+body, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_user_state(user_id)
    context.user_data.setdefault("chat_history", [])
    context.user_data.setdefault("current_npc", None)
    await update.message.reply_text(
        "🏢 *Pixel Office* | ใช้ปุ่มเมนู\n\n"
        "💡 บอทโหลดข้อมูลตลาดและข่าวทุก 1 นาทีอัตโนมัติ (ไม่ต้องรอ refresh) การตอบจะเร็วและทันสมัย\n"
        "เลือก NPC → ถามคำถาม → พิมพ์ต่อเนื่องได้เลย",
        reply_markup=main_menu(), parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    state = get_user_state(user_id)

    # Dossier
    if data == "dossiers":
        kb = [
            [InlineKeyboardButton("📋 ดูทั้งหมด", callback_data="dossier_view_all")],
            [InlineKeyboardButton("👤 ดูตาม NPC", callback_data="dossier_filter_npc")],
            [InlineKeyboardButton("🔍 ค้นหา", callback_data="dossier_search")],
            [InlineKeyboardButton("🔙 กลับ", callback_data="refresh")]
        ]
        await query.edit_message_text("🗂️ *Dossier*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return
    elif data == "dossier_view_all":
        await show_dossier_page(update, user_id, 0, "all", None)
        return
    elif data == "dossier_filter_npc":
        kb = [[InlineKeyboardButton(npc_name(n), callback_data=f"dossier_npc_{n}")] for n in ["macro","portfolio","hedge","tech","alt","zen"]]
        kb.append([InlineKeyboardButton("🔙 กลับ", callback_data="dossiers")])
        await query.edit_message_text("เลือก NPC:", reply_markup=InlineKeyboardMarkup(kb))
        return
    elif data.startswith("dossier_npc_"):
        npc = data.split("_")[2]
        await show_dossier_page(update, user_id, 0, npc, None)
        return
    elif data == "dossier_search":
        context.user_data["search_mode"] = True
        await query.edit_message_text("🔍 พิมพ์คำค้นหา:")
        return
    elif data.startswith("dossier_page_"):
        page = int(data.split("_")[2])
        npc_filter = context.user_data.get("dossier_npc_filter", "all")
        keyword = context.user_data.get("dossier_keyword")
        await show_dossier_page(update, user_id, page, npc_filter, keyword)
        return

    # Tasks
    if data == "tasks":
        tasks = get_tasks_by_status(user_id)
        await query.edit_message_text(format_task_list(tasks, "📋 *ภารกิจทั้งหมด*"), reply_markup=main_menu(), parse_mode="Markdown")
    elif data == "overload":
        tasks = get_tasks_by_status(user_id, "overload")
        await query.edit_message_text(format_task_list(tasks, "⚠️ *OVERLOAD*"), reply_markup=main_menu(), parse_mode="Markdown")
    elif data == "blocked":
        tasks = get_tasks_by_status(user_id, "blocked")
        await query.edit_message_text(format_task_list(tasks, "🔒 *BLOCKED*"), reply_markup=main_menu(), parse_mode="Markdown")
    elif data == "add_task":
        context.user_data["awaiting_task"] = True
        await query.edit_message_text("✏️ พิมพ์ชื่อภารกิจ (พิมพ์ /cancel)")
    elif data == "update_task":
        tasks = get_tasks_by_status(user_id)
        if not tasks:
            await query.edit_message_text("ไม่มีภารกิจ", reply_markup=main_menu())
            return
        kb = [[InlineKeyboardButton(f"#{t['id']} {t['title'][:20]}", callback_data=f"select_task_{t['id']}")] for t in tasks]
        kb.append([InlineKeyboardButton("🔙 กลับ", callback_data="refresh")])
        await query.edit_message_text("เลือกภารกิจ:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("select_task_"):
        task_id = int(data.split("_")[2])
        context.user_data["updating_task_id"] = task_id
        await query.edit_message_text(f"เลือกสถานะใหม่สำหรับ #{task_id}:", reply_markup=task_action_menu(task_id))
    elif data.startswith("task_status_"):
        parts = data.split("_")
        task_id = int(parts[2])
        new_status = parts[3]
        if update_task_status(user_id, task_id, new_status):
            await query.edit_message_text(f"✅ อัปเดต #{task_id} เป็น {new_status}", reply_markup=main_menu())
        else:
            await query.edit_message_text("ไม่พบภารกิจ", reply_markup=main_menu())
    elif data == "refresh":
        # Force refresh cache (clear cache)
        set_cached_news([], ttl=0)
        set_cached_market("", ttl=0)
        await query.edit_message_text(f"🔄 กำลังโหลดข้อมูลใหม่...\n{datetime.now().strftime('%H:%M:%S')}", reply_markup=main_menu())
        # Also trigger immediate background refresh
        asyncio.create_task(background_data_refresh_once())
    elif data == "team":
        team_text = "👥 *ทีม:*\n" + "\n".join([f"- {m['name']} ({m['role']}) {m['progress']}%" for m in state['team']])
        await query.edit_message_text(team_text, reply_markup=main_menu(), parse_mode="Markdown")
    elif data == "floor":
        await query.edit_message_text(f"🏢 ชั้น {state['floor']} (อัปเกรด 500 credits)", reply_markup=main_menu())
    elif data == "ask_team":
        await query.edit_message_text("เลือก NPC หรือเรียกทีม:", reply_markup=npc_menu())
    elif data.startswith("npc_"):
        npc_code = data.split("_")[1]
        context.user_data["current_npc"] = npc_code
        context.user_data["chat_history"] = []
        kb = [[InlineKeyboardButton("🔚 ออกจาก NPC", callback_data="exit_npc")]]
        await query.edit_message_text(f"✅ กำลังคุยกับ {npc_name(npc_code)}\nพิมพ์คำถามได้เลย (บอทจำบทสนทนา)\nกดปุ่มด้านล่างเพื่อออก", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "exit_npc":
        context.user_data.pop("current_npc", None)
        context.user_data.pop("chat_history", None)
        await query.edit_message_text("ออกจากการสนทนา กลับเมนูหลัก", reply_markup=main_menu())
    elif data == "team_all":
        context.user_data["awaiting_all_team"] = True
        await query.edit_message_text("👥 พิมพ์คำถามที่ต้องการให้ทีมวิเคราะห์:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ยกเลิก", callback_data="refresh")]]))
    else:
        await query.edit_message_text(f"⚙️ กำลังพัฒนา: {data}", reply_markup=main_menu())

async def background_data_refresh_once():
    await background_data_refresh()  # reuse the same function but run once

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if text.startswith("/cancel"):
        context.user_data.pop("current_npc", None)
        context.user_data.pop("awaiting_task", None)
        context.user_data.pop("updating_task_id", None)
        context.user_data.pop("search_mode", None)
        context.user_data.pop("awaiting_all_team", None)
        await update.message.reply_text("ยกเลิกแล้ว กลับเมนู", reply_markup=main_menu())
        return

    # Search mode
    if context.user_data.get("search_mode"):
        context.user_data["search_mode"] = False
        keyword = text.strip()
        dossiers = get_dossiers(user_id, "all", keyword)
        if not dossiers:
            await update.message.reply_text("ไม่พบข้อมูล", reply_markup=main_menu())
            return
        msg = f"🔍 ผลค้นหา '{keyword}':\n" + "\n".join(format_dossier_entry(d, i+1) for i,d in enumerate(dossiers[:10]))
        if len(dossiers)>10: msg += f"\n... และอีก {len(dossiers)-10} รายการ"
        await update.message.reply_text(msg, reply_markup=main_menu(), parse_mode="Markdown")
        return

    # Add task
    if context.user_data.get("awaiting_task"):
        title = text.strip()
        if not title:
            await update.message.reply_text("ชื่อไม่ถูกต้อง")
            return
        state = get_user_state(user_id)
        team_members = [m["name"] for m in state["team"]]
        assigned = team_members[0] if team_members else "BP-006"
        new_task = add_task(user_id, title, assigned)
        await update.message.reply_text(f"✅ เพิ่มภารกิจ #{new_task['id']}: {title}")
        context.user_data.pop("awaiting_task")
        return

    # ASK ALL TEAM
    if context.user_data.get("awaiting_all_team"):
        context.user_data.pop("awaiting_all_team")
        question = text.strip()
        progress = await update.message.reply_text("👥 กำลังเรียกประชุมทีม (ใช้เวลา 20-30 วินาที)...")
        try:
            # ใช้ cache ที่ background อัปเดตให้แล้ว
            news = await asyncio.to_thread(fetch_recent_news_sync, 6, use_cache=True)
            market = await asyncio.to_thread(get_market_summary_sync, use_cache=True)
            answer = await ask_all_team_async(question, news, market)
            await progress.edit_text(answer[:4096])
        except Exception as e:
            await progress.edit_text(f"เกิดข้อผิดพลาด: {str(e)[:200]}")
        return

    # Normal NPC chat
    npc = context.user_data.get("current_npc")
    if npc:
        progress = await update.message.reply_text("🔍 กำลังวิเคราะห์... (15-20 วินาที)")
        try:
            news = await asyncio.to_thread(fetch_recent_news_sync, 6, use_cache=True)
            market = await asyncio.to_thread(get_market_summary_sync, use_cache=True)
            history = context.user_data.get("chat_history", [])
            answer = await ask_deepseek_async(text, npc, news, market, history)
            # Save dossier
            state = get_user_state(user_id)
            state["dossiers"].append({
                "npc": npc, "question": text, "answer": answer,
                "timestamp": datetime.now().isoformat()
            })
            save_user_state(user_id, state)
            # Update history
            new_history = history + [{"role": "user", "content": text}, {"role": "assistant", "content": answer}]
            if len(new_history) > 8:
                new_history = new_history[-8:]
            context.user_data["chat_history"] = new_history
            await progress.edit_text(answer[:4096])
        except Exception as e:
            await progress.edit_text(f"Error: {str(e)[:200]}")
    else:
        await update.message.reply_text("กรุณาเลือก NPC จากเมนู 📈 ASK TEAM ก่อน", reply_markup=main_menu())

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("ยกเลิกทั้งหมด กลับเมนู", reply_markup=main_menu())

def main():
    if not TOKEN:
        print("Missing TOKEN")
        return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    # Start background data refresher
    loop = asyncio.get_event_loop()
    loop.create_task(background_data_refresh())
    print("Pixel Bot (Background Refresh + Google News) started.")
    app.run_polling()

if __name__ == "__main__":
    main()
