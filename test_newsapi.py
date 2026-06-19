import os
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY = os.getenv("NEWS_API_KEY")

def test_news_api():
    to_time = datetime.now(timezone.utc)
    from_time = to_time - timedelta(hours=6)
    
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": "stock market OR economy OR central bank OR inflation OR GDP OR PMI OR employment OR earnings OR geopolitics OR commodity",
        "sources": "bloomberg,cnbc,financial-times,reuters,associated-press,bbc-news",
        "from": from_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": to_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sortBy": "publishedAt",
        "pageSize": 30,
        "language": "en",
        "apiKey": NEWS_API_KEY
    }
    
    print(f"กำลังดึงข่าวในช่วง {from_time} ถึง {to_time}")
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        data = response.json()
        total_results = data.get('totalResults', 0)
        articles = data.get('articles', [])
        print(f"พบข่าวทั้งหมด {total_results} ข่าว")
        print(f"ดึงข้อมูลมา {len(articles)} ข่าว")
        
        if len(articles) > 0:
            print("\nตัวอย่างข่าวที่ 1:")
            print(f"หัวข้อ: {articles[0].get('title')}")
            print(f"เวลาที่เผยแพร่: {articles[0].get('publishedAt')}")
            print(f"แหล่งที่มา: {articles[0].get('source', {}).get('name')}")
        else:
            print("ไม่พบบทความข่าว")
    else:
        print(f"Error: {response.status_code}")
        print(f"ข้อความ: {response.text}")

if __name__ == "__main__":
    test_news_api()
