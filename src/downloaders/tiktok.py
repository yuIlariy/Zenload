"""TikTok downloader - API + Cobalt + yt-dlp fallback"""

import os
import re
import logging
import asyncio
import aiohttp
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse
import yt_dlp
from .base import BaseDownloader, DownloadError
from ..utils.cobalt_service import cobalt

logger = logging.getLogger(__name__)


class TikTokDownloader(BaseDownloader):

    def platform_id(self) -> str:
        return 'tiktok'

    def __init__(self):
        super().__init__()

        self.cookies_path = Path(__file__).parent.parent.parent / "cookies" / "tiktok.txt"

        self.info_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }

    def can_handle(self, url: str) -> bool:
        return "tiktok.com" in url

    def preprocess_url(self, url: str) -> str:
        return url.split('?')[0]

    # ✅ FORMAT NUMBERS
    def format_number(self, num):
        try:
            num = int(num)
        except:
            return None

        if num >= 1_000_000:
            return f"{num/1_000_000:.1f}M"
        if num >= 1_000:
            return f"{num/1_000:.1f}K"
        return str(num)

    # 🔥 NEW: API SCRAPER (REAL FIX)
    async def fetch_stats_api(self, url: str):
        try:
            api_url = f"https://www.tiktok.com/oembed?url={url}"

            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, timeout=10) as resp:
                    data = await resp.json()

            # ⚠️ oEmbed doesn't include stats, so we fallback to HTML scrape
            return None, None

        except Exception as e:
            logger.warning(f"[TikTok] API failed: {e}")
            return None, None

    # 🔥 HTML SCRAPER (THIS IS THE REAL POWER)
    async def scrape_stats_html(self, url: str):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as resp:
                    text = await resp.text()

            # Extract JSON from page
            match = re.search(r'"playCount":(\d+)', text)
            views = match.group(1) if match else None

            match = re.search(r'"diggCount":(\d+)', text)
            likes = match.group(1) if match else None

            return self.format_number(views), self.format_number(likes)

        except Exception as e:
            logger.warning(f"[TikTok] HTML scrape failed: {e}")
            return None, None

    # 🔥 FINAL STATS GETTER
    async def get_stats(self, url, info):
        # 1. Try yt-dlp
        views = info.get('view_count') or info.get('play_count')
        likes = info.get('like_count') or info.get('digg_count')

        if views or likes:
            return self.format_number(views), self.format_number(likes)

        # 2. Try HTML scrape
        views, likes = await self.scrape_stats_html(url)

        return views, likes

    def build_caption(self, url, title=None, username=None, views=None, likes=None):
        parts = ["🎵 <b>TikTok Video</b>\n"]

        if title:
            parts.append(f"📝 {title.split(' #')[0]}\n\n")

        if username:
            parts.append(f"👤 <b>@{username}</b>\n")

        if views or likes:
            stats = []
            if views:
                stats.append(f"👁 {views}")
            if likes:
                stats.append(f"❤️ {likes}")
            parts.append(" | ".join(stats) + "\n")
        else:
            parts.append("👁 N/A | ❤️ N/A\n")

        parts.append(f"\n🔗 <a href=\"{url}\">Watch on TikTok</a>\n")
        parts.append("\n📥 <b>@Tik_TokDownloader_Bot</b>")

        return "".join(parts)

    async def _get_video_info(self, url):
        try:
            def extract():
                with yt_dlp.YoutubeDL(self.info_opts) as ydl:
                    return ydl.extract_info(url, download=False)

            return await asyncio.to_thread(extract)
        except:
            return {}

    async def download(self, url, format_id=None):
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)

        info = await self._get_video_info(url)

        title = info.get('description') or info.get('title')
        username = (info.get('uploader') or "").replace('@', '')

        # 🔥 USE NEW STATS SYSTEM
        views, likes = await self.get_stats(url, info)

        # 1. COBALT
        filename, file_path = await cobalt.download(
            url,
            download_dir,
            progress_callback=self.update_progress,
            tiktok_watermark=False
        )

        if file_path and file_path.exists():
            return self.build_caption(url, title, username, views, likes), file_path

        # 2. yt-dlp fallback
        temp_filename = f"tiktok_{os.urandom(4).hex()}"

        ydl_opts = {
            'format': 'best',
            'outtmpl': str(download_dir / f"{temp_filename}.%(ext)s"),
            'quiet': True,
            'no_warnings': True,
            'cookiefile': str(self.cookies_path) if self.cookies_path.exists() else None,
        }

        def run():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=True)

        info = await asyncio.to_thread(run)

        for file in download_dir.glob(f"{temp_filename}.*"):
            if file.is_file():
                return self.build_caption(
                    url,
                    info.get('title'),
                    info.get('uploader'),
                    views,
                    likes
                ), file

        raise DownloadError("Download failed")
