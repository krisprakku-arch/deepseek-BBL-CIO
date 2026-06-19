#!/bin/bash
cd ~/deepseek-agent
source venv/bin/activate

# หยุดทุก process ที่เกี่ยวข้อง
pkill -9 -f "pixel_bot.py"
pkill -9 -f "telegram_bot.py"
screen -ls | grep -E "pixel|bot" | awk -F '.' '{print $1}' | xargs -I {} screen -X -S {} quit

# ล้าง webhook (ใช้ token จาก .env)
source .env
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/deleteWebhook" > /dev/null

# รอสักครู่ให้แน่ใจว่าเคลียร์แล้ว
sleep 2

# เริ่มบอทด้วย nohup (ไม่ต้อง screen)
nohup python3 pixel_bot.py > pixel_bot.log 2>&1 &
echo "Pixel Bot started with nohup. Log: pixel_bot.log"
