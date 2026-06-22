import os
import logging
import threading
from flask import Flask
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from dotenv import load_dotenv
from orchestrator import run_orchestrator

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ---------- Handlers ----------
async def start(update, context):
    await update.message.reply_text("🏢 Pixel Bot on Render! พิมพ์คำถามได้เลย")

async def handle_text(update, context):
    text = update.message.text
    progress = await update.message.reply_text("🤖 กำลังคิด...")
    try:
        answer = run_orchestrator(text, [])
        await progress.edit_text(answer[:4096])
    except Exception as e:
        await progress.edit_text(f"Error: {str(e)[:200]}")

# ---------- Flask endpoint (เพื่อให้ UptimeRobot ปิง) ----------
@app.route('/')
def index():
    return "Pixel Bot is running!"

# ---------- ฟังก์ชันรันบอท (Polling) ----------
def run_bot():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot polling started")
    application.run_polling()

# ---------- Main ----------
if __name__ == '__main__':
    # เริ่มบอทใน thread แยก
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # รัน Flask
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
