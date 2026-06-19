import json
import os
from datetime import datetime

CALENDAR_FILE = "calendar.json"

def load_calendar():
    if not os.path.exists(CALENDAR_FILE):
        return []
    with open(CALENDAR_FILE, "r") as f:
        return json.load(f)

def save_calendar(events):
    with open(CALENDAR_FILE, "w") as f:
        json.dump(events, f, indent=2)

def add_event(title, date_str, time_str=None):
    events = load_calendar()
    events.append({
        "title": title,
        "date": date_str,
        "time": time_str,
        "created": datetime.now().isoformat()
    })
    save_calendar(events)
    return f"✅ เพิ่มนัด: {title} ในวันที่ {date_str} {time_str or ''}"

def get_today_events():
    today = datetime.now().strftime("%Y-%m-%d")
    events = load_calendar()
    today_events = [e for e in events if e["date"] == today]
    if not today_events:
        return "วันนี้ไม่มีนัดหมาย"
    return "\n".join([f"- {e['title']} เวลา {e['time']}" for e in today_events])
