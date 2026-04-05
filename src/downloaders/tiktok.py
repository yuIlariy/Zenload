"""TikTok downloader - FIXED (stable + stats safe)"""

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
            logger.info("[TikTok] Cookies loaded")
        else:
            logger.warning("[TikTok] No cookies found")

    # ✅ FIXED DOMAIN HANDLING
    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(
            parsed.netloc and
            any(domain in parsed.netloc.lower()
                for domain in ['tiktok.com', 'vt.tiktok.com', 'vm.tiktok.com'])
        )

    def preprocess_url(self, url: str) -> str:
        if any(x in url for x in ["vt.tiktok.com", "vm.tiktok.com"]):
            return url
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

    # ✅ CAPTION
    def build_caption(self, url, title=None, username=None, views=None, likes=None):
        parts = ["🎵 <b>TikTok Video</b>\n"]

        if title:
            parts.append(f"📝 {title.split(' #')[0]}\n\n")

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

    async def get_formats(self, url: str) -> List[Dict]:
        return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        logger.info(f"[TikTok] Downloading: {url}")

        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)

        # 🔥 1. TRY COBALT (FAST)
        try:
            filename, file_path = await cobalt.download(
                url,
                download_dir,
                progress_callback=self.update_progress,
                tiktok_watermark=False
            )

            if file_path and file_path.exists():
                # ⚠️ Don't block — return immediately
                caption = self.build_caption(url)
                return caption, file_path

        except Exception as e:
            logger.warning(f"[TikTok] Cobalt failed: {e}")

        # 🔥 2. FALLBACK TO yt-dlp (ONLY IF NEEDED)
        logger.info("[TikTok] Falling back to yt-dlp")

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

        try:
            info = await asyncio.to_thread(run)

            views = self.format_number(info.get('view_count'))
            likes = self.format_number(info.get('like_count'))
            username = (info.get('uploader') or "").replace('@', '')
            title = info.get('description') or info.get('title')

            for file in download_dir.glob(f"{temp_filename}.*"):
                if file.is_file():
                    caption = self.build_caption(url, title, username, views, likes)
                    return caption, file

        except Exception as e:
            logger.error(f"[TikTok] yt-dlp failed: {e}")
            raise DownloadError("Download failed")

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
