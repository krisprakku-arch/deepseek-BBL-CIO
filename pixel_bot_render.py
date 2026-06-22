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

# ---------- สร้าง Application ----------
telegram_app = Application.builder().token(TOKEN).build()

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

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

# ---------- Webhook (ใช้ run_until_complete) ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, telegram_app.bot)
        # ใช้ asyncio.run() (Python 3.7+) แทนการสร้าง loop เอง
        asyncio.run(telegram_app.process_update(update))
        return 'ok', 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'error', 500

@app.route('/')
def index():
    return "Pixel Bot is running!"

# ---------- Main ----------
if __name__ == '__main__':
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    # Initialize Application
    async def init():
        await telegram_app.initialize()
        await telegram_app.start()
        webhook_url = os.getenv("WEBHOOK_URL")
        if webhook_url:
            await telegram_app.bot.set_webhook(url=webhook_url)
            logger.info(f"Webhook set to {webhook_url}")

    asyncio.run(init())
    logger.info("Application initialized")

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
