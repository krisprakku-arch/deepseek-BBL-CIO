import os
import logging
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from dotenv import load_dotenv
from orchestrator import run_orchestrator
import asyncio
import sys

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ---------- สร้าง Application (จะ Initialize ทีหลัง) ----------
telegram_app = None

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

# ---------- Webhook (สร้าง Event Loop ใหม่ทุกครั้ง) ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    global telegram_app
    if telegram_app is None:
        return 'error: app not initialized', 500
    try:
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, telegram_app.bot)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(telegram_app.process_update(update))
            return 'ok', 200
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'error', 500

@app.route('/')
def index():
    return "Pixel Bot is running!"

def set_webhook():
    global telegram_app
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        logger.error("WEBHOOK_URL not set")
        return
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(telegram_app.bot.set_webhook(url=webhook_url))
        logger.info(f"Webhook set to {webhook_url}")
    finally:
        loop.close()

# ---------- Main ----------
if __name__ == '__main__':
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    # สร้าง Application
    telegram_app = Application.builder().token(TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Initialize Application ใน Event Loop ใหม่
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(telegram_app.initialize())
        loop.run_until_complete(telegram_app.start())
        logger.info("Telegram Application initialized and started")
    except Exception as e:
        logger.error(f"Initialization error: {e}")
        sys.exit(1)
    finally:
        loop.close()

    # ตั้ง Webhook
    set_webhook()

    # รัน Flask
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
