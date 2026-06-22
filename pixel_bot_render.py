import os
import logging
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from orchestrator import run_orchestrator

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ---------- สร้าง Application (ใช้ async แต่เราจะใช้ sync wrapper) ----------
telegram_app = Application.builder().token(TOKEN).build()

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏢 Pixel Bot on Render! พิมพ์คำถามได้เลย")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    progress = await update.message.reply_text("🤖 กำลังคิด...")
    try:
        answer = run_orchestrator(text, [])
        await progress.edit_text(answer[:4096])
    except Exception as e:
        await progress.edit_text(f"Error: {str(e)[:200]}")

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

# ---------- Sync Wrapper สำหรับ Webhook ----------
def process_update_sync(update: Update) -> None:
    """ประมวลผล Update โดยใช้ event loop ใหม่แบบ sync"""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(telegram_app.process_update(update))
    finally:
        loop.close()

# ---------- Webhook (sync) ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, telegram_app.bot)
        process_update_sync(update)
        return 'ok', 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'error', 500

@app.route('/')
def index():
    return "Pixel Bot is running!"

def set_webhook():
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        logger.error("WEBHOOK_URL not set")
        return
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(telegram_app.bot.set_webhook(url=webhook_url))
        logger.info(f"Webhook set to {webhook_url}")
    finally:
        loop.close()

if __name__ == '__main__':
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        exit(1)
    
    # Initialize Application
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(telegram_app.initialize())
        loop.run_until_complete(telegram_app.start())
        logger.info("Telegram Application started")
    finally:
        loop.close()
    
    set_webhook()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
