"""TikTok downloader - Cobalt API primary, yt-dlp fallback"""

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

        # 🔥 TikTok cookies path (LIKE INSTAGRAM)
        self.cookies_path = Path(__file__).parent.parent.parent / "cookies" / "tiktok.txt"

        if self.cookies_path.exists():
            logger.info(f"[TikTok] Found cookies at {self.cookies_path}")
        else:
            logger.warning("[TikTok] No cookies file found!")

        self.info_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(parsed.netloc and "tiktok.com" in parsed.netloc)

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

    # 🔥 STRONG STATS EXTRACTION
    def extract_stats(self, info: Dict[str, Any]):
        views = (
            info.get('view_count')
            or info.get('play_count')
            or info.get('views')
            or info.get('statistics', {}).get('viewCount')
        )

        likes = (
            info.get('like_count')
            or info.get('likes')
            or info.get('digg_count')
            or info.get('statistics', {}).get('likeCount')
        )

        return self.format_number(views), self.format_number(likes)

    # 🔥 CAPTION BUILDER
    def build_caption(self, url: str, title=None, username=None, views=None, likes=None):
        parts = ["🎵 <b>TikTok Video</b>\n"]

        if title:
            clean = title.split(' #')[0]
            parts.append(f"📝 {clean}\n\n")

        if username:
            parts.append(f"👤 <b>@{username}</b>\n")

        stats = []
        if views:
            stats.append(f"👁 {views}")
        if likes:
            stats.append(f"❤️ {likes}")

        if stats:
            parts.append(" | ".join(stats) + "\n")
        else:
            parts.append("👁 N/A | ❤️ N/A\n")

        parts.append(f"\n🔗 <a href=\"{url}\">Watch on TikTok</a>\n")
        parts.append("\n📥 <b>@Tik_TokDownloader_Bot</b>")

        return "".join(parts)

    async def _get_video_info(self, url: str) -> Dict[str, Any]:
        try:
            def extract():
                with yt_dlp.YoutubeDL(self.info_opts) as ydl:
                    return ydl.extract_info(url, download=False)

            return await asyncio.to_thread(extract)
        except Exception as e:
            logger.error(f"[TikTok] Metadata failed: {e}")
            return {}

    async def get_formats(self, url: str) -> List[Dict]:
        return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        logger.info(f"[TikTok] Downloading: {url}")

        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)

        # 1. METADATA
        info = await self._get_video_info(url)

        title = info.get('description') or info.get('title')
        username = (info.get('uploader') or "").replace('@', '').strip()

        views, likes = self.extract_stats(info)

        # 2. COBALT FIRST
        filename, file_path = await cobalt.download(
            url,
            download_dir,
            progress_callback=self.update_progress,
            tiktok_watermark=False
        )

        if file_path and file_path.exists():
            return self.build_caption(url, title, username, views, likes), file_path

        # 3. 🔥 YT-DLP FALLBACK (WITH COOKIES + RETRIES)
        logger.info("[TikTok] Fallback → yt-dlp")

        temp_filename = f"tiktok_{os.urandom(4).hex()}"

        ydl_opts = {
            'format': 'best',
            'outtmpl': str(download_dir / f"{temp_filename}.%(ext)s"),
            'quiet': True,
            'no_warnings': True,
            'cookiefile': str(self.cookies_path) if self.cookies_path.exists() else None,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0'
            },
            'progress_hooks': [self._progress_hook],
        }

        def run():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=True)

        # 🔁 RETRY SYSTEM
        for attempt in range(3):
            try:
                info = await asyncio.to_thread(run)
                break
            except Exception as e:
                logger.warning(f"[TikTok] Retry {attempt+1}: {e}")
                if attempt == 2:
                    raise DownloadError("yt-dlp failed after retries")
                await asyncio.sleep(2)

        # FIND FILE
        for file in download_dir.glob(f"{temp_filename}.*"):
            if file.is_file():
                views, likes = self.extract_stats(info)

                return self.build_caption(
                    url,
                    info.get('description') or info.get('title'),
                    (info.get('uploader') or "").replace('@', '').strip(),
                    views,
                    likes
                ), file

        raise DownloadError("File not found")

    def _progress_hook(self, d: Dict[str, Any]):
        if d['status'] == 'downloading':
            try:
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)

                if total > 0:
                    percent = int((downloaded / total) * 100)
                    self.update_progress('status_downloading', percent)
            except:
                pass
