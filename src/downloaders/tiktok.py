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

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(
            parsed.netloc and
            any(domain in parsed.netloc.lower()
                for domain in ['tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'])
        )

    def preprocess_url(self, url: str) -> str:
        return url.split('?')[0]

    def format_number(self, num):
        if not num:
            return "0"
        if num >= 1_000_000:
            return f"{num/1_000_000:.1f}M"
        if num >= 1_000:
            return f"{num/1_000:.1f}K"
        return str(num)

    # 🔥 CLEAN CAPTION (MAIN FIX)
    def build_caption(self, url: str, username: str = None, views=None, likes=None):
        parts = ["🎵 <b>TikTok Video</b>\n"]

        if username:
            parts.append(f"👤 <b>{username}</b>\n")

        if views or likes:
            stats = []
            if views:
                stats.append(f"👁 {views}")
            if likes:
                stats.append(f"❤️ {likes}")
            parts.append(" | ".join(stats) + "\n")

        parts.append(f"\n🔗 <a href=\"{url}\">Watch on TikTok</a>\n")
        parts.append("\n📥 <b>@Tik_TokDownloader_Bot</b>")

        return "".join(parts)

    async def get_formats(self, url: str) -> List[Dict]:
        self.update_progress('status_getting_info', 0)

        result = await cobalt.request(url)
        if result.success:
            self.update_progress('status_getting_info', 100)
            return [{'id': 'best', 'quality': 'Best (No watermark)', 'ext': 'mp4'}]

        return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        logger.info(f"[TikTok] Downloading: {url}")
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)

        # === COBALT FIRST ===
        self.update_progress('status_downloading', 10)

        filename, file_path = await cobalt.download(
            url,
            download_dir,
            progress_callback=self.update_progress,
            tiktok_watermark=False
        )

        if file_path and file_path.exists():
            metadata = self.build_caption(url)
            return metadata, file_path

        # === FALLBACK YT-DLP ===
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

            info = await asyncio.to_thread(download_video)

            if not info:
                raise DownloadError("Download failed")

            for file in download_dir.glob(f"{temp_filename}.*"):
                if file.is_file():

                    username = info.get('uploader', '')
                    username = username.replace('https://www.tiktok.com/@', '').strip()

                    views = self.format_number(info.get('view_count', 0))
                    likes = self.format_number(info.get('like_count', 0))

                    metadata = self.build_caption(
                        url=url,
                        username=username,
                        views=views,
                        likes=likes
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
