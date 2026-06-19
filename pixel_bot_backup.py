import os
import logging
import json
import feedparser
import yfinance as yf
import re
import asyncio
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

# ---------- Static Knowledge Base ----------
INVESTMENT_KNOWLEDGE = """
หลักการลงทุนสำคัญ:
1. Modern Portfolio Theory: การกระจายการลงทุนในสินทรัพย์ที่ไม่มี correlation สูง ช่วยลดความเสี่ยงโดยไม่ลดผลตอบแทนที่คาดหวัง
2. Value Investing (Benjamin Graham): ซื้อหุ้นเมื่อราคาต่ำกว่ามูลค่าที่แท้จริง (P/E, P/B ต่ำกว่า historical average)
3. Dollar Cost Averaging (DCA): ลงทุนจำนวนเงินเท่าๆ กันเป็นประจำ ไม่พยายามจับจังหวะตลาด ลดความเสี่ยงจากการลงทุนครั้งเดียว
4. Risk Management: ไม่ควรลงทุนเกิน 2-5% ของพอร์ตในหุ้นตัวเดียว และตั้ง stop loss ที่ 7-10%
5. Sharpe Ratio: วัดผลตอบแทนส่วนเกินต่อความเสี่ยง ควรเลือกพอร์ตที่มี Sharpe สูงกว่า 1
6. Technical Indicators: RSI >70 เกิด overbought, <30 เกิด oversold; MACD ตัดขึ้นเป็นสัญญาณซื้อ
7. Behavioral Biases: Loss aversion (กลัวขาดทุนมากกว่าอยากได้กำไร), Herding (ทำตามหมู่), Confirmation bias (เสพข่าวที่สอดคล้อง) ควรตระหนักและลดอคติ
8. Asset Allocation ตามอายุ: อายุน้อย risk ทนได้ ควรหุ้นสูง (80/20) อายุใกล้เกษียณ เพิ่มพันธบัตร (40/60)
9. Emergency Fund: ก่อนลงทุน ควรมีเงินสำรองฉุกเฉิน 3-6 เดือนของค่าใช้จ่าย เพื่อไม่ต้องขายสินทรัพย์ในภาวะตกต่ำ
10. REITs: การลงทุนในอสังหาริมทรัพย์ผ่านกองทุน มีสภาพคล่องดี ให้ผลตอบแทนจากค่าเช่า มักมีความสัมพันธ์ต่ำกับหุ้น
11. Dividend Investing: การลงทุนในหุ้นที่จ่ายปันผลสม่ำเสมอ ช่วยสร้างกระแสเงินสดและลดความผันผวนในระยะยาว
12. Global Diversification: การลงทุนในต่างประเทศช่วยลดความเสี่ยงเฉพาะประเทศ และเพิ่มโอกาสรับการเติบโตจากตลาดอื่น
"""

# ---------- Game State (JSON) ----------
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
            "credits": 100
        }
        save_data(data)
    return data[uid]

def save_user_state(user_id, state):
    data = load_data()
    data[str(user_id)] = state
    save_data(data)

# ---------- Real-time News & Market Data (with timeouts) ----------
RSS_FEEDS = {
    "Reuters Business": "http://feeds.reuters.com/reuters/businessNews",
    "CNBC Economy": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "Investing.com": "https://www.investing.com/rss/news.rss",
}

def fetch_recent_news_sync(hours=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    articles = []
    for src, url in RSS_FEEDS.items():
        try:
            import socket
            socket.setdefaulttimeout(10)
            feed = feedparser.parse(url)
            socket.setdefaulttimeout(None)
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
                    "published": pub.strftime('%Y-%m-%d %H:%M UTC') if pub else 'เวลาล่าสุด'
                })
        except Exception as e:
            logger.error(f"RSS {src} error: {e}")
    seen = set()
    unique = []
    for a in articles:
        key = a['title'][:80].lower()
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique[:20]

def get_market_summary_sync():
    indices = {"S&P500": "^GSPC", "NASDAQ": "^IXIC", "Dow Jones": "^DJI"}
    lines = []
    for name, sym in indices.items():
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="1d")
            if not hist.empty:
                price = hist['Close'].iloc[-1]
                prev = hist['Close'].iloc[-2] if len(hist) > 1 else price
                change = (price - prev) / prev * 100
                lines.append(f"{name}: {price:.2f} ({change:+.2f}%)")
            else:
                lines.append(f"{name}: ไม่มีข้อมูล")
        except Exception as e:
            lines.append(f"{name}: ดึงข้อมูลไม่ได้")
    return "\n".join(lines) if lines else "ไม่สามารถดึงข้อมูลตลาดได้"

def filter_news_by_keywords(question, articles, top_k=3):
    keywords = set(re.findall(r'\w+', question.lower()))
    stopwords = {'จะ','และ','หรือ','ใน','ของ','ที่','มี','ได้','ไม่','การ','เป็น','ให้','ว่า','ซึ่ง','เมื่อ','เรา','คุณ','ผม','ค่ะ','ครับ'}
    keywords = [kw for kw in keywords if kw not in stopwords and len(kw) > 1]
    scored = []
    for a in articles:
        text = (a['title'] + ' ' + a['summary']).lower()
        score = sum(1 for kw in keywords if kw in text)
        scored.append((score, a))
    # เรียงลำดับตาม score (มากไปน้อย) โดยใช้ key แทนการเปรียบเทียบ tuple โดยตรง (ปลอดภัย)
    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored[:top_k]]

# ---------- NPC System Prompts (with personality) ----------
NPC_SYSTEM_PROMPTS = {
    "macro": f"""คุณคือ Dr. Macro นักเศรษฐศาสตร์มหภาค พูดจาฉะฉาน สุขุม เน้นตัวเลขเศรษฐกิจ ใช้น้ำเสียงเหมือนนักวิเคราะห์ Bloomberg
คุณตอบโดยอิงทฤษฎีเศรษฐศาสตร์, ดัชนีชี้วัด, GDP, Inflation, Fed policy, yield curve
ตัวอย่างการพูด: "จากข้อมูล PMI ล่าสุดที่หดตัว ตลาดแรงงานยังตึงตัว Fed อาจคงอัตราดอกเบี้ยไปจนถึง Q3..."
ความรู้ที่มี:
{INVESTMENT_KNOWLEDGE}
""",
    "portfolio": f"""คุณคือ Ms. Portfolio ผู้เชี่ยวชาญด้านการจัดพอร์ตลงทุน คุณให้คำแนะนำด้วยตัวเลข พูดจาเป็นกันเองแต่มีความรู้ลึก
คุณอธิบาย Modern Portfolio Theory, strategic/tactical asset allocation, risk parity ได้ชัดเจน
ตัวอย่างการพูด: "พอร์ตของคุณมีสัดส่วนหุ้น 80% อาจลดเหลือ 60% โดยเพิ่มพันธบัตรรัฐบาลเพื่อให้ Sharpe ratio ดีขึ้น..."
ความรู้ที่มี:
{INVESTMENT_KNOWLEDGE}
""",
    "hedge": f"""คุณคือ Mr. Hedge ผู้จัดการความเสี่ยง พูดจาตรงไปตรงมา เน้นตัวเลขความเสี่ยง, stop loss, hedging instruments
คุณไม่ชอบความเสี่ยงที่ไม่ได้รับผลตอบแทนที่เหมาะสม
ตัวอย่างการพูด: "การตั้ง stop loss ที่ 7% และใช้ protective put จะช่วยลด downside risk โดยไม่เสีย upside..."
ความรู้ที่มี:
{INVESTMENT_KNOWLEDGE}
""",
    "tech": f"""คุณคือ Candle Master นักวิเคราะห์ทางเทคนิค พูดเร็ว กระตือรือร้น ใช้ภาษาเทรดเดอร์
คุณเชี่ยวชาญ candlestick patterns, RSI, MACD, Bollinger Bands, Fibonacci
ตัวอย่างการพูด: "กราฟรายวันเกิด bullish engulfing ที่แนวรับ 200-day EMA พร้อม RSI ดีดตัวจาก 32 — น่าสนใจ!"
ความรู้ที่มี:
{INVESTMENT_KNOWLEDGE}
""",
    "alt": f"""คุณคือ Miss Gold & Crypto ผู้เชี่ยวชาญสินทรัพย์ทางเลือก พูดตื่นเต้นเหมือนเล่าเรื่องขุมทรัพย์
คุณวิเคราะห์ทองคำ, Bitcoin, Ethereum, DeFi, NFT อย่างสนุกสนาน
ตัวอย่างการพูด: "BTC กำลังทดสอบแนวต้าน $70k ถ้าผ่านได้ มีลุ้นไป $75k ในสัปดาห์หน้า! แต่อย่าลืม stop loss นะ"
ความรู้ที่มี:
{INVESTMENT_KNOWLEDGE}
""",
    "zen": f"""คุณคือ Zen Investor นักปรัชญาการลงทุน พูดช้าๆ สุขุม เน้นจิตวิทยาและวินัย
คุณชอบอ้างอิง Buffett, Charlie Munger, Peter Lynch
ตัวอย่างการพูด: "ความกลัวของตลาดคือโอกาสของผู้มีวินัย ... จำคำของ Buffett ไหมครับ 'Be fearful when others are greedy'"
ความรู้ที่มี:
{INVESTMENT_KNOWLEDGE}
"""
}

# ---------- Async DeepSeek Call with timeout ----------
async def ask_deepseek_async(question, npc_code, news_articles, market_data, history=[]):
    system_prompt = NPC_SYSTEM_PROMPTS.get(npc_code, f"คุณคือผู้เชี่ยวชาญด้านการลงทุน ตอบอย่างมืออาชีพ\n{INVESTMENT_KNOWLEDGE}")
    relevant_news = filter_news_by_keywords(question, news_articles, top_k=4)
    news_text = ""
    for i, a in enumerate(relevant_news, 1):
        news_text += f"{i}. [{a['source']}] {a['title']} ({a['published']})\n   {a['summary']}\n\n"
    
    user_content = f"""ข้อมูลตลาดวันนี้:
{market_data}

ข่าวที่เกี่ยวข้องกับคำถาม:
{news_text if news_text else 'ไม่มีข่าวที่เกี่ยวข้องโดยตรง'}

คำถาม: {question}

ช่วยตอบเป็นภาษาไทย สไตล์ของคุณ ด้วยทฤษฎี/หลักการที่ถูกต้อง กระชับ แต่มีชีวิตชีวา"""
    
    messages = [{"role": "system", "content": system_prompt}]
    # ใช้ history ได้สูงสุด 6 ข้อความล่าสุด (ไม่ใช่การเปรียบเทียบ)
    if history and len(history) > 0:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": user_content})
    
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.75,
                max_tokens=800
            ),
            timeout=20.0
        )
        return resp.choices[0].message.content
    except asyncio.TimeoutError:
        return "ขออภัย การวิเคราะห์ใช้เวลานานเกินไป (เกิน 20 วินาที) กรุณาถามคำถามสั้นลง หรือลองใหม่อีกครั้งครับ"
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return f"ขออภัย เกิดข้อผิดพลาดในการติดต่อระบบวิเคราะห์: {type(e).__name__}"

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
        [InlineKeyboardButton("📈 Dr. Macro (Economy)", callback_data="npc_macro")],
        [InlineKeyboardButton("🧠 Ms. Portfolio (Strategy)", callback_data="npc_portfolio")],
        [InlineKeyboardButton("⚖️ Mr. Hedge (Risk)", callback_data="npc_hedge")],
        [InlineKeyboardButton("📊 Candle Master (Tech)", callback_data="npc_tech")],
        [InlineKeyboardButton("💎 Miss Gold & Crypto", callback_data="npc_alt")],
        [InlineKeyboardButton("🧘 Zen Investor", callback_data="npc_zen")],
        [InlineKeyboardButton("👥 ASK ALL TEAM", callback_data="team_all")],
        [InlineKeyboardButton("🔙 Back", callback_data="refresh")]
    ]
    return InlineKeyboardMarkup(keyboard)

def npc_name(code):
    return {
        "macro": "Dr. Macro (Macroeconomics)",
        "portfolio": "Ms. Portfolio (Strategy)",
        "hedge": "Mr. Hedge (Risk)",
        "tech": "Candle Master (Technical)",
        "alt": "Miss Gold & Crypto",
        "zen": "Zen Investor (Behavioral)"
    }.get(code, "NPC")

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    context.user_data["chat_history"] = []
    msg = f"🏢 *Pixel Office Command Center*   Floor {state['floor']}\n"
    msg += f"👥 Team: {len(state['team'])} | Tasks: {len(state['tasks'])} | 💰 {state['credits']} credits\n"
    msg += "\nเลือกคำสั่งด้านล่าง:"
    await update.message.reply_text(msg, reply_markup=main_menu(), parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    state = get_user_state(user_id)

    if data == "refresh":
        msg = f"🔄 อัปเดตเมื่อ {datetime.now().strftime('%H:%M:%S')}\n"
        msg += f"ชั้น {state['floor']} | ทีม {len(state['team'])} | งาน {len(state['tasks'])}"
        await query.edit_message_text(msg, reply_markup=main_menu())
    elif data == "team":
        team_text = "👥 *ทีมของคุณ:*\n"
        for m in state['team']:
            team_text += f"- {m['name']} ({m['role']}) ความคืบหน้า {m['progress']}%\n"
        await query.edit_message_text(team_text, reply_markup=main_menu(), parse_mode="Markdown")
    elif data == "floor":
        await query.edit_message_text(f"🏢 คุณอยู่ชั้น {state['floor']}\nอัปเกรดต้องใช้ 500 credits", reply_markup=main_menu())
    elif data == "ask_team":
        await query.edit_message_text("เลือก NPC ที่ต้องการปรึกษา:", reply_markup=npc_menu())
    elif data.startswith("npc_"):
        npc_code = data.split("_")[1]
        context.user_data["current_npc"] = npc_code
        context.user_data["chat_history"] = []
        await query.edit_message_text(f"คุณกำลังคุยกับ {npc_name(npc_code)}\nพิมพ์คำถาม (พิมพ์ /cancel เพื่อออก)")
    elif data == "team_all":
        await query.edit_message_text("⚙️ ฟีเจอร์ถามทุกคนกำลังพัฒนา", reply_markup=main_menu())
    else:
        await query.edit_message_text(f"⚙️ กำลังพัฒนา: {data}", reply_markup=main_menu())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if text.startswith("/cancel"):
        context.user_data.pop("current_npc", None)
        context.user_data.pop("chat_history", None)
        await update.message.reply_text("ยกเลิกการสนทนา กลับสู่เมนูหลัก", reply_markup=main_menu())
        return

    npc = context.user_data.get("current_npc")
    if npc:
        progress_msg = await update.message.reply_text("🔍 กำลังรวบรวมข้อมูล... (กรุณารอสักครู่)")
        try:
            # โหลดข้อมูล (ใช้ thread pool)
            news = await asyncio.to_thread(fetch_recent_news_sync, 24)
            market = await asyncio.to_thread(get_market_summary_sync)
            history = context.user_data.get("chat_history", [])
            answer = await ask_deepseek_async(text, npc, news, market, history)
            # บันทึก dossier
            state = get_user_state(user_id)
            state["dossiers"].append({
                "npc": npc,
                "question": text,
                "answer": answer,
                "timestamp": datetime.now().isoformat()
            })
            save_user_state(user_id, state)
            # อัปเดตประวัติ (เก็บเป็น list ของ dict)
            new_history = history.copy()
            new_history.append({"role": "user", "content": text})
            new_history.append({"role": "assistant", "content": answer})
            if len(new_history) > 6:
                new_history = new_history[-6:]
            context.user_data["chat_history"] = new_history
            # แก้ไขข้อความ progress เป็นคำตอบ
            await progress_msg.edit_text(answer[:4096])
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            await progress_msg.edit_text(f"เกิดข้อผิดพลาด: {str(e)[:200]}")
    else:
        await update.message.reply_text("กรุณาใช้ปุ่มเมนู หรือพิมพ์ /start")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("current_npc", None)
    context.user_data.pop("chat_history", None)
    await update.message.reply_text("ยกเลิกแล้ว", reply_markup=main_menu())

# ---------- Main ----------
def main():
    if not TOKEN:
        print("Missing TELEGRAM_BOT_TOKEN")
        return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Pixel Bot started (async, timeout 20s, fixed sorting).")
    app.run_polling()

if __name__ == "__main__":
    main()
