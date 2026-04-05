"""TikTok downloader - Cobalt API primary, yt-dlp fallback"""

import re
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
        # Options optimized for fast metadata extraction
        self.info_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'extract_flat': False,
        }

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(
            parsed.netloc and
            any(domain in parsed.netloc.lower()
                for domain in ['tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'])
        )

    def format_number(self, num):
        """Standardizes large numbers into K/M format"""
        if not num:
            return "0"
        if num >= 1_000_000:
            return f"{num/1_000_000:.1f}M"
        if num >= 1_000:
            return f"{num/1_000:.1f}K"
        return str(num)

    def build_caption(self, url: str, title: str = None, username: str = None, views=None, likes=None):
        """Constructs the final Telegram caption with stats"""
        parts = ["🎵 <b>TikTok Video</b>\n"]

        if title:
            # Clean title to remove hashtags for a cleaner look
            clean_title = title.split(' #')[0] if ' #' in title else title
            parts.append(f"📝 {clean_title}\n\n")

        if username:
            parts.append(f"👤 <b>@{username}</b>\n")

        stats = []
        if views and views != "0":
            stats.append(f"👁 {views}")
        if likes and likes != "0":
            stats.append(f"❤️ {likes}")
        
        if stats:
            parts.append(" | ".join(stats) + "\n")

        parts.append(f"\n🔗 <a href=\"{url}\">Watch on TikTok</a>\n")
        parts.append("\n📥 <b>@Tik_TokDownloader_Bot</b>")

        return "".join(parts)

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        logger.info(f"[TikTok] Downloading: {url}")
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)

        # 1. NON-BLOCKING METADATA PRE-FETCH
        # We use asyncio.to_thread to prevent the bot from freezing here
        self.update_progress('status_getting_info', 20)
        
        info = {}
        try:
            def extract():
                with yt_dlp.YoutubeDL(self.info_opts) as ydl:
                    return ydl.extract_info(url, download=False)
            
            # This was the blocking call causing the freeze
            info = await asyncio.to_thread(extract) 
        except Exception as e:
            logger.error(f"[TikTok] Metadata pre-fetch failed: {e}")

        # Extract values for the caption
        title = info.get('description') or info.get('title')
        raw_user = info.get('uploader') or info.get('uploader_id', 'User')
        username = raw_user.replace('@', '').strip() if raw_user else "User"
        views = self.format_number(info.get('view_count'))
        likes = self.format_number(info.get('like_count'))

        # 2. Try Cobalt for the actual file
        self.update_progress('status_downloading', 10)
        filename, file_path = await cobalt.download(
            url,
            download_dir,
            progress_callback=self.update_progress,
            tiktok_watermark=False
        )

        if file_path and file_path.exists():
            # Use the pre-fetched metadata even when Cobalt succeeds
            metadata = self.build_caption(url, title, username, views, likes)
            return metadata, file_path

        # 3. Fallback to yt-dlp
        logger.info("[TikTok] Cobalt failed → yt-dlp fallback")
        self.update_progress('status_downloading', 30)

        try:
            temp_filename = f"tiktok_{os.urandom(4).hex()}"
            ydl_opts = {
                'format': format_id or 'best',
                'outtmpl': str(download_dir / f"{temp_filename}.%(ext)s"),
                'quiet': True,
                'no_warnings': True,
                'progress_hooks': [self._progress_hook],
            }

            def download_video():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=True)

            # Use to_thread again to prevent freezing during fallback
            info = await asyncio.to_thread(download_video)

            for file in download_dir.glob(f"{temp_filename}.*"):
                if file.is_file():
                    metadata = self.build_caption(
                        url=url,
                        title=info.get('description') or info.get('title'),
                        username=info.get('uploader', '').replace('@', '').strip(),
                        views=self.format_number(info.get('view_count')),
                        likes=self.format_number(info.get('like_count'))
                    )
                    return metadata, file

            raise DownloadError("File not found")

        except Exception as e:
            logger.error(f"[TikTok] Download failed: {e}")
            raise DownloadError(f"Download error: {str(e)}")

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
