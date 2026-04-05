"""TikTok downloader - FINAL FIX (stats from yt-dlp download)"""

import os
import logging
import asyncio
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

        # ✅ cookies path
        self.cookies_path = Path(__file__).parent.parent.parent / "cookies" / "tiktok.txt"

        if self.cookies_path.exists():
            logger.info(f"[TikTok] Cookies loaded")
        else:
            logger.warning("[TikTok] No cookies found")

    def can_handle(self, url: str) -> bool:
        return "tiktok.com" in url

    def preprocess_url(self, url: str) -> str:
        return url.split('?')[0]

    # ✅ number formatter
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

    # ✅ caption
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

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        logger.info(f"[TikTok] Downloading: {url}")

        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)

        # 🔥 1. TRY COBALT (FAST)
        filename, file_path = await cobalt.download(
            url,
            download_dir,
            progress_callback=self.update_progress,
            tiktok_watermark=False
        )

        # ⚠️ DO NOT TRUST COBALT FOR STATS
        if file_path and file_path.exists():
            # fallback stats = none (we'll still try yt-dlp for stats)
            logger.info("[TikTok] Cobalt success, fetching stats via yt-dlp...")

        # 🔥 2. ALWAYS RUN yt-dlp FOR STATS + FALLBACK DOWNLOAD
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

        # 🔁 retries
        for attempt in range(3):
            try:
                info = await asyncio.to_thread(run)
                break
            except Exception as e:
                logger.warning(f"[TikTok] Retry {attempt+1}: {e}")
                if attempt == 2:
                    raise DownloadError("yt-dlp failed")
                await asyncio.sleep(2)

        # 🔥 extract stats (THIS IS THE FIX)
        views = self.format_number(info.get('view_count'))
        likes = self.format_number(info.get('like_count'))
        username = (info.get('uploader') or "").replace('@', '')
        title = info.get('description') or info.get('title')

        # 🔥 if cobalt already gave file, use it
        if file_path and file_path.exists():
            return self.build_caption(url, title, username, views, likes), file_path

        # otherwise use yt-dlp file
        for file in download_dir.glob(f"{temp_filename}.*"):
            if file.is_file():
                return self.build_caption(url, title, username, views, likes), file

        raise DownloadError("Download failed")
