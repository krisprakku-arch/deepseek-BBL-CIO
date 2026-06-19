import os
import logging
import json
from datetime import datetime
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

# ---------- Game State (minimal) ----------
DATA_FILE = "game_data_minimal.json"

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

# ---------- Task functions ----------
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

# ---------- AI call (fast, no external data) ----------
async def ask_deepseek(question, history=[]):
    system_prompt = "คุณคือผู้ช่วยด้านการลงทุนที่ตอบสั้น กระชับ เป็นมิตร ใช้ภาษาไทย ไม่แนะนำการซื้อขายเฉพาะตัว"
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": question})
    try:
        resp = await client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.7,
            max_tokens=300
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return f"ขออภัย เกิดข้อผิดพลาด: {type(e).__name__}"

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
        [InlineKeyboardButton("💬 ASK BOT", callback_data="ask_bot")]
    ]
    return InlineKeyboardMarkup(keyboard)

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

# ---------- Dossier (simple) ----------
def get_dossiers(user_id):
    state = get_user_state(user_id)
    return sorted(state.get("dossiers", []), key=lambda x: x.get("timestamp",""), reverse=True)

def format_dossier_entry(entry, idx):
    ts = entry.get("timestamp","")[:16].replace("T"," ")
    q = entry.get("question","")[:80]
    return f"{idx}. [{ts}] {q}\n"

async def show_dossier(update, user_id):
    dossiers = get_dossiers(user_id)
    if not dossiers:
        await update.callback_query.edit_message_text("🗂️ ไม่มีรายการ", reply_markup=main_menu())
        return
    text = "🗂️ *ประวัติคำถามล่าสุด*\n\n"
    for i, d in enumerate(dossiers[:10], 1):
        text += format_dossier_entry(d, i)
    if len(dossiers) > 10:
        text += f"\n... และอีก {len(dossiers)-10} รายการ"
    await update.callback_query.edit_message_text(text, reply_markup=main_menu(), parse_mode="Markdown")

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_user_state(user_id)
    context.user_data["chat_history"] = []
    await update.message.reply_text(
        "🏢 *Pixel Office Minimal* | ใช้ปุ่มเมนู\n\n"
        "💬 กด 'ASK BOT' แล้วพิมพ์คำถามเกี่ยวกับการลงทุนได้เลย (ตอบไว ไม่ดึงข่าว/หุ้น)",
        reply_markup=main_menu(), parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    state = get_user_state(user_id)

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
        await query.edit_message_text(f"🔄 อัปเดต {datetime.now().strftime('%H:%M:%S')}", reply_markup=main_menu())
    elif data == "team":
        team_text = "👥 *ทีม:*\n" + "\n".join([f"- {m['name']} ({m['role']}) {m['progress']}%" for m in state['team']])
        await query.edit_message_text(team_text, reply_markup=main_menu(), parse_mode="Markdown")
    elif data == "floor":
        await query.edit_message_text(f"🏢 ชั้น {state['floor']} (อัปเกรด 500 credits)", reply_markup=main_menu())
    elif data == "dossiers":
        await show_dossier(update, user_id)
    elif data == "ask_bot":
        context.user_data["chatting_with_bot"] = True
        await query.edit_message_text("💬 คุณกำลังคุยกับบอท (พิมพ์คำถามได้เลย พิมพ์ /cancel เพื่อออก)", reply_markup=main_menu())
    else:
        await query.edit_message_text(f"⚙️ กำลังพัฒนา: {data}", reply_markup=main_menu())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if text.startswith("/cancel"):
        context.user_data.pop("awaiting_task", None)
        context.user_data.pop("updating_task_id", None)
        context.user_data.pop("chatting_with_bot", None)
        await update.message.reply_text("ยกเลิกแล้ว กลับเมนู", reply_markup=main_menu())
        return

    # Add task mode
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

    # Chat with bot (general investment Q&A)
    if context.user_data.get("chatting_with_bot"):
        progress = await update.message.reply_text("🤔 กำลังคิด...")
        history = context.user_data.get("chat_history", [])
        answer = await ask_deepseek(text, history)
        # Save to dossier
        state = get_user_state(user_id)
        state["dossiers"].append({
            "npc": "bot",
            "question": text,
            "answer": answer,
            "timestamp": datetime.now().isoformat()
        })
        save_user_state(user_id, state)
        # Update history
        new_history = history + [{"role": "user", "content": text}, {"role": "assistant", "content": answer}]
        if len(new_history) > 10:
            new_history = new_history[-10:]
        context.user_data["chat_history"] = new_history
        await progress.edit_text(answer[:4096])
    else:
        await update.message.reply_text("กรุณากดปุ่ม 'ASK BOT' ในเมนูเพื่อเริ่มคุย", reply_markup=main_menu())

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
    print("Minimal Pixel Bot started (fast, no external data).")
    app.run_polling()

if __name__ == "__main__":
    main()
