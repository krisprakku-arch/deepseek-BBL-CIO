#!/usr/bin/env python3
import feedparser
from datetime import datetime, timedelta
import time
import sys

RSS_SOURCES = {
    "Reuters Business": "http://feeds.reuters.com/reuters/businessNews",
    "Reuters Company News": "http://feeds.reuters.com/reuters/companyNews",
    "Reuters Technology": "http://feeds.reuters.com/reuters/technologyNews",
    "Yahoo Finance Top Stories": "https://finance.yahoo.com/news/rssindex",
    "CNBC Finance": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",  # Economy feed
    "CNBC Markets": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100011142",     # Markets feed
    "Fox Business": "https://moxie.foxbusiness.com/google-rss/foxbusiness.xml",
    "Investing.com Latest": "https://www.investing.com/rss/news.rss",
}

def fetch_rss_news(hours_back=6):
    """Fetch articles from all RSS sources and return them as a list"""
    cutoff_time = datetime.now() - timedelta(hours=hours_back)
    all_articles = []
    
    for source_name, feed_url in RSS_SOURCES.items():
        try:
            feed = feedparser.parse(feed_url)
            print(f"✅ Parsed {source_name}: {len(feed.entries)} entries")
            
            for entry in feed.entries:
                try:
                    # Parse publish date (if available)
                    pub_time = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        pub_time = datetime(*entry.published_parsed[:6])
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        pub_time = datetime(*entry.updated_parsed[:6])
                    
                    # Skip if older than cutoff (if we have a date)
                    if pub_time and pub_time < cutoff_time:
                        continue
                    
                    all_articles.append({
                        "title": entry.get("title", ""),
                        "description": entry.get("summary", entry.get("description", "")),
                        "source": source_name,
                        "publishedAt": pub_time.isoformat() if pub_time else datetime.now().isoformat(),
                        "link": entry.get("link", "")
                    })
                except Exception as e:
                    print(f"   ⚠️ Error parsing entry in {source_name}: {e}")
                    continue
                    
        except Exception as e:
            print(f"❌ Failed to fetch {source_name}: {e}")
    
    # Remove duplicates based on title (simple dedup)
    seen_titles = set()
    unique_articles = []
    for article in all_articles:
        title_key = article["title"].lower()[:100]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_articles.append(article)
    
    print(f"📰 Total unique articles fetched: {len(unique_articles)}")
    return unique_articles

def test_rss_feeds():
    """Quick test function to verify feeds work"""
    articles = fetch_rss_news(hours_back=12)
    print(f"\n✅ Successfully fetched {len(articles)} articles in last 12 hours")
    
    if articles:
        print("\n📌 First 3 articles:")
        for i, article in enumerate(articles[:3], 1):
            print(f"\n{i}. [{article['source']}] {article['title']}")
            print(f"   Time: {article['publishedAt']}")
    else:
        print("\n⚠️ No articles found. Possible causes:")
        print("   - RSS feed URLs may have changed")
        print("   - Network connectivity issue")
        print("   - Articles are older than time window")

if __name__ == "__main__":
    test_rss_feeds()

