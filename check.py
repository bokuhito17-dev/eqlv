import json
import os
import re
from urllib.parse import parse_qs, urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

VIDEO_WEBHOOK_URL = os.environ.get("DISCORD_VIDEO_WEBHOOK_URL", "").strip()
NEWS_WEBHOOK_URL = os.environ.get("DISCORD_NEWS_WEBHOOK_URL", "").strip()

PLAYER_BASE_URL = "https://bokuhito17-dev.github.io/eqlv/"
HISTORY_FILE = "notified.json"
YOUTUBE_CHANNELS = [
    ("＝LOVE公式ch", "UCv7VutirxDn3RWIJXI68n_A"),
    ("イコノイジョイch", "UCWHh6SdvJWrPuf1oJrHbX3A"),
]
NEWS_URL = "https://equal-love.jp/news/"
YOUTUBE_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
VIDEO_ID_PATTERN = re.compile(r"^[0-9A-Za-z_-]{11}$")


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return set()

    with open(HISTORY_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("notified.json must contain a JSON list.")

    return set(data)


def save_history(notified):
    with open(HISTORY_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(notified), file, ensure_ascii=False, indent=2)
        file.write("\n")


def require_webhook(name, value):
    if not value:
        raise RuntimeError(
            f"{name} is empty. Check the corresponding GitHub Actions secret."
        )


def send_discord_message(webhook_url, content):
    response = requests.post(
        webhook_url,
        json={
            "content": content,
            "allowed_mentions": {"parse": []},
        },
        timeout=20,
    )
    response.raise_for_status()


def get_video_id(entry):
    video_id = entry.get("yt_videoid")
    if not video_id:
        query = parse_qs(urlparse(entry.get("link", "")).query)
        video_id = query.get("v", [""])[0]

    return video_id if VIDEO_ID_PATTERN.fullmatch(video_id or "") else None


def collect_new_videos(notified):
    new_videos = []
    queued_urls = set()

    for channel_name, channel_id in YOUTUBE_CHANNELS:
        rss_url = YOUTUBE_RSS_URL.format(channel_id=channel_id)
        response = requests.get(
            rss_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        if feed.bozo and not feed.entries:
            raise RuntimeError(f"Could not parse YouTube RSS for {channel_name}.")

        for entry in feed.entries[:5]:
            video_id = get_video_id(entry)
            if not video_id:
                print(f"Skipping an entry without a valid video ID: {channel_name}")
                continue

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            if video_url in notified or video_url in queued_urls:
                continue

            player_url = f"{PLAYER_BASE_URL}?v={video_id}"
            title = " ".join(entry.get("title", "新着動画").split())
            message = (
                f"🎬 **【{channel_name}】** {title}\n"
                f"▶ [無菌専用プレイヤーで開く]({player_url})"
            )
            new_videos.append((video_url, message))
            queued_urls.add(video_url)

    return new_videos


def collect_new_news(notified):
    response = requests.get(
        NEWS_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding

    soup = BeautifulSoup(response.text, "html.parser")
    new_news = []
    queued_urls = set()

    for anchor in soup.select("a[href*='/news/detail/']")[:8]:
        article_url = urljoin(NEWS_URL, anchor.get("href", ""))
        parsed_url = urlparse(article_url)

        if parsed_url.netloc not in ("equal-love.jp", "www.equal-love.jp"):
            continue

        title = " ".join(anchor.get_text(" ", strip=True).split())
        if not title or article_url in notified or article_url in queued_urls:
            continue

        message = (
            f"📢 **【＝LOVE公式NEWS】** {title}\n"
            f"▶ [公式サイトで記事を読む]({article_url})"
        )
        new_news.append((article_url, message))
        queued_urls.add(article_url)

    return new_news


def deliver_items(webhook_url, items, notified, label):
    delivered = 0

    for item_url, message in items:
        # Save each successful delivery immediately. If a later request fails,
        # the workflow can still commit the history of messages already sent.
        send_discord_message(webhook_url, message)
        notified.add(item_url)
        save_history(notified)
        delivered += 1
        print(f"Sent {label}: {item_url}")

    return delivered


def main():
    require_webhook("DISCORD_VIDEO_WEBHOOK_URL", VIDEO_WEBHOOK_URL)
    require_webhook("DISCORD_NEWS_WEBHOOK_URL", NEWS_WEBHOOK_URL)

    notified = load_history()

    new_videos = collect_new_videos(notified)
    new_news = collect_new_news(notified)

    video_count = deliver_items(
        VIDEO_WEBHOOK_URL, new_videos, notified, "video notification"
    )
    news_count = deliver_items(
        NEWS_WEBHOOK_URL, new_news, notified, "NEWS notification"
    )

    print(
        "Check completed. "
        f"New videos: {video_count}; new NEWS articles: {news_count}."
    )


if __name__ == "__main__":
    main()
