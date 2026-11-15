import os
import re
import json
import feedparser
import requests
from bs4 import BeautifulSoup

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
# Step 4 で発行される自分の GitHub Pages のURLに書き換える
PLAYER_BASE_URL = "https://bokuhito17-dev.github.io/eqlv/"
HISTORY_FILE = "notified.json"

if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        notified = set(json.load(f))
else:
    notified = set()

new_messages = []

# 1. YouTube 2チャンネルのRSSチェック
channels = [
    ("＝LOVE公式ch", "UCv7VutirxDn3RWIJXI68n_A"),
    ("イコノイジョイch", "UCWHh6SdvJWrPuf1oJrHbX3A")
]

for ch_name, ch_id in channels:
    rss_url = f"https://youtube.com{ch_id}"
    feed = feedparser.parse(rss_url)
    for entry in feed.entries[:5]:
        video_url = entry.link
        if video_url not in notified:
            match = re.search(r"v=([0-9A-Za-z_-]{11})", video_url)
            video_id = match.group(1) if match else ""
            clean_link = f"{PLAYER_BASE_URL}?v={video_id}"
            new_messages.append(f"🎬 **【{ch_name}】** {entry.title}\n▶ 無菌プレイヤーで開く: {clean_link}")
            notified.add(video_url)

# 2. ＝LOVE公式サイトのニュースチェック
news_url = "https://equal-love.jp/news/"
headers = {"User-Agent": "Mozilla/5.0"}
res = requests.get(news_url, headers=headers)
res.encoding = res.apparent_encoding
soup = BeautifulSoup(res.text, "html.parser")

for a_tag in soup.select("a[href*='/news/detail/']")[:8]:
    href = a_tag.get("href", "")
    full_url = "https://equal-love.jp" + href if href.startswith("/") else href
    title = " ".join(a_tag.get_text().split())
    if title and full_url not in notified:
        new_messages.append(f"📢 **【公式NEWS】** {title}\n🔗 {full_url}")
        notified.add(full_url)

# 3. 新着があればDiscordへ送信して履歴を更新
if new_messages:
    payload = {"content": "\n\n".join(new_messages)}
    requests.post(WEBHOOK_URL, json=payload)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(notified), f, ensure_ascii=False, indent=2)
