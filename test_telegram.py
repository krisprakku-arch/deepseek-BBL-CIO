import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TOKEN or not CHAT_ID:
    print("❌ กรุณาตั้งค่า TELEGRAM_BOT_TOKEN และ TELEGRAM_CHAT_ID ในไฟล์ .env")
else:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": "Hello from your script! ✅"}
    response = requests.post(url, data=data)
    if response.status_code == 200:
        print("✅ ส่งข้อความสำเร็จ ไปดูใน Telegram เลย")
    else:
        print(f"❌ ส่งไม่สำเร็จ: {response.text}")
