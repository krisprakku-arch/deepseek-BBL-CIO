import schedule
import time
from news_briefing import run_briefing

schedule.every().day.at("07:00").do(run_briefing)
schedule.every().day.at("13:00").do(run_briefing)
schedule.every().day.at("17:00").do(run_briefing)

print("⏰ ระบบสรุปข่าวเริ่มทำงาน จะส่งรายงานเวลา 7:00, 13:00, 17:00 น.")
while True:
    schedule.run_pending()
    time.sleep(60)
