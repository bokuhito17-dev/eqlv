import json
import os
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

VIDEO_WEBHOOK_URL = os.environ.get("DISCORD_VIDEO_WEBHOOK_URL", "").strip()
NEWS_WEBHOOK_URL = os.environ.get("DISCORD_NEWS_WEBHOOK_URL", "").strip()
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()

PLAYER_BASE_URL = "https://bokuhito17-dev.github.io/eqlv/"
HISTORY_FILE = "notified.json"
VIDEO_BASELINE_FILE = "video_baseline.json"
YOUTUBE_CHANNELS = [
    ("＝LOVE公式ch", "UCv7VutirxDn3RWIJXI68n_A"),
    ("イコノイジョイch", "UCWHh6SdvJWrPuf1oJrHbX3A"),
]
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
NEWS_URL = "https://equal-love.jp/news/"
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


def load_video_baseline():
    if not os.path.exists(VIDEO_BASELINE_FILE):
        return False

    with open(VIDEO_BASELINE_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)

    return isinstance(data, dict) and data.get("initialized") is True


def save_video_baseline():
    with open(VIDEO_BASELINE_FILE, "w", encoding="utf-8") as file:
        json.dump({"initialized": True}, file, indent=2)
        file.write("\n")


def require_webhook(name, value):
    if not value:
        raise RuntimeError(
            f"{name} is empty. Check the corresponding GitHub Actions secret."
        )


def youtube_api_get(endpoint, params, context):
    request_params = dict(params)
    request_params["key"] = YOUTUBE_API_KEY

    try:
        response = requests.get(
            f"{YOUTUBE_API_BASE_URL}/{endpoint}",
            params=request_params,
            timeout=20,
        )
    except requests.RequestException as error:
        # Do not print the exception text: request URLs can contain the API key.
        raise RuntimeError(
            f"YouTube Data API request failed for {context} "
            f"({type(error).__name__})."
        ) from None

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            f"YouTube Data API returned a non-JSON response for {context} "
            f"(HTTP {response.status_code})."
        ) from None

    if not response.ok:
        error_data = data.get("error", {}) if isinstance(data, dict) else {}
        message = error_data.get("message", "No error message provided.")
        reasons = [
            item.get("reason")
            for item in error_data.get("errors", [])
            if isinstance(item, dict) and item.get("reason")
        ]
        reason_text = ", ".join(reasons) if reasons else "unknown"
        raise RuntimeError(
            f"YouTube Data API request failed for {context} "
            f"(HTTP {response.status_code}; reason={reason_text}; "
            f"message={message}). Check the API key, API activation, and quota."
        )

    if not isinstance(data, dict):
        raise RuntimeError(
            f"YouTube Data API returned an unexpected response for {context}."
        )

    return data


def get_uploads_playlist_id(channel_name, channel_id):
    data = youtube_api_get(
        "channels",
        {
            "part": "contentDetails",
            "id": channel_id,
        },
        f"channel lookup: {channel_name}",
    )

    channels = data.get("items", [])
    if not channels:
        raise RuntimeError(
            f"YouTube Data API returned no channel for {channel_name} "
            f"({channel_id}). Check the configured channel ID."
        )

    uploads_id = (
        channels[0]
        .get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )
    if not uploads_id:
        raise RuntimeError(
            f"Could not find the uploads playlist for {channel_name}."
        )

    return uploads_id


def get_latest_channel_videos(channel_name, channel_id):
    uploads_id = get_uploads_playlist_id(channel_name, channel_id)
    data = youtube_api_get(
        "playlistItems",
        {
            "part": "snippet,contentDetails",
            "playlistId": uploads_id,
            "maxResults": 5,
        },
        f"uploads playlist: {channel_name}",
    )

    items = data.get("items", [])
    if not items:
        raise RuntimeError(
            f"YouTube Data API returned no uploads for {channel_name}. "
            "Refusing to treat an empty result as a valid video check."
        )

    videos = []
    for item in items:
        snippet = item.get("snippet", {})
        content_details = item.get("contentDetails", {})
        resource_id = snippet.get("resourceId", {})
        video_id = (
            content_details.get("videoId")
            or resource_id.get("videoId")
        )

        if not VIDEO_ID_PATTERN.fullmatch(video_id or ""):
            print(f"Skipping an item without a valid video ID for {channel_name}.")
            continue

        title = " ".join(snippet.get("title", "新着動画").split())
        videos.append((video_id, title))

    if not videos:
        raise RuntimeError(
            f"YouTube Data API returned no usable video IDs for {channel_name}."
        )

    print(
        f"YouTube Data API diagnostic for {channel_name}: "
        f"uploads_playlist_items={len(items)}, usable_videos={len(videos)}."
    )
    return videos


def collect_new_videos(notified):
    new_videos = []
    queued_urls = set()

    for channel_name, channel_id in YOUTUBE_CHANNELS:
        videos = get_latest_channel_videos(channel_name, channel_id)

        for video_id, title in videos:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            if video_url in notified:
                print(f"Already recorded video for {channel_name}: {video_id}")
                continue
            if video_url in queued_urls:
                continue

            player_url = f"{PLAYER_BASE_URL}?v={video_id}"
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


def send_discord_message(webhook_url, content):
    response = requests.post(
        webhook_url,
        json={
            "content": content,
            "allowed_mentions": {"parse": []},
        },
        headers={
            "User-Agent": "DiscordBot (https://github.com/bokuhito17-dev/eqlv, 1.0)",
        },
        timeout=20,
    )
    response.raise_for_status()


def main():
    require_webhook("DISCORD_VIDEO_WEBHOOK_URL", VIDEO_WEBHOOK_URL)
    require_webhook("DISCORD_NEWS_WEBHOOK_URL", NEWS_WEBHOOK_URL)
    require_webhook("YOUTUBE_API_KEY", YOUTUBE_API_KEY)

    notified = load_history()
    new_videos = collect_new_videos(notified)

    # On the first API-based run, record the latest uploads as a baseline
    # instead of flooding Discord with older videos.
    if not load_video_baseline():
        if not new_videos:
            raise RuntimeError(
                "No YouTube videos were returned; refusing to initialize the video baseline."
            )
        for video_url, _ in new_videos:
            notified.add(video_url)
        save_history(notified)
        save_video_baseline()
        print(
            f"Initialized YouTube baseline with {len(new_videos)} existing videos. "
            "They were not sent as new-video notifications."
        )
        new_videos = []

    new_news = collect_new_news(notified)

    video_count = deliver_items(
        VIDEO_WEBHOOK_URL, new_videos, notified, "video notification"
    )

    # Announce an empty result only after both YouTube channels were checked
    # successfully. API/network errors raise earlier and never reach this point.
    if video_count == 0:
        send_discord_message(
            VIDEO_WEBHOOK_URL,
            "ℹ️ **今回の確認では新着動画はありませんでした。**\n"
            "＝LOVE公式ch・イコノイジョイchを確認しました。",
        )
        print("Sent no-new-videos announcement.")

    news_count = deliver_items(
        NEWS_WEBHOOK_URL, new_news, notified, "NEWS notification"
    )

    print(
        "Check completed. "
        f"New videos: {video_count}; new NEWS articles: {news_count}."
    )


if __name__ == "__main__":
    main()
