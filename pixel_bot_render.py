import os
import logging
from flask import Flask, request
import telegram
from dotenv import load_dotenv
from orchestrator import run_orchestrator
import json

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ---------- สร้าง Bot (ไม่ต้อง Application) ----------
bot = telegram.Bot(token=TOKEN)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update_data = request.get_json(force=True)
        update = telegram.Update.de_json(update_data, bot)

        # ดึงข้อความและ chat_id
        if update.message and update.message.text:
            chat_id = update.message.chat.id
            text = update.message.text

            # ถ้าเป็น /start
            if text.startswith('/start'):
                bot.send_message(chat_id=chat_id, text="🏢 Pixel Bot on Render! พิมพ์คำถามได้เลย")
            else:
                # ส่งข้อความ "กำลังคิด"
                progress_msg = bot.send_message(chat_id=chat_id, text="🤖 กำลังคิด...")
                try:
                    answer = run_orchestrator(text, [])
                    bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=answer[:4096])
                except Exception as e:
                    bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=f"Error: {str(e)[:200]}")
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
    try:
        bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to {webhook_url}")
    except Exception as e:
        logger.error(f"Set webhook error: {e}")

if __name__ == '__main__':
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        exit(1)
    set_webhook()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
