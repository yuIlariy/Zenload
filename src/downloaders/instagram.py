"""Instagram downloader using Cobalt API with yt-dlp fallback"""

import re
import logging
import asyncio
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import yt_dlp

from .base import BaseDownloader, DownloadError
from ..utils.cobalt_service import cobalt

logger = logging.getLogger(__name__)


class InstagramDownloader(BaseDownloader):
    """Instagram downloader using Cobalt API with yt-dlp fallback"""
    
    def __init__(self):
        super().__init__()
        self.ydl_opts.update({
            'format': 'best',
            'nooverwrites': True,
            'quiet': True,
            'no_warnings': True,
        })

    def _extract_shortcode(self, url: str) -> Optional[str]:
        """Extract shortcode from Instagram URL"""
        patterns = [
            r'instagram\.com/p/([A-Za-z0-9_-]+)',
            r'instagram\.com/reel/([A-Za-z0-9_-]+)',
            r'instagram\.com/reels/([A-Za-z0-9_-]+)',
            r'instagram\.com/tv/([A-Za-z0-9_-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def platform_id(self) -> str:
        return 'instagram'

    def can_handle(self, url: str) -> bool:
        return any(x in url for x in ["instagram.com", "instagr.am"])

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats"""
        self.update_progress('status_getting_info', 0)
        
        # Try Cobalt first
        result = await cobalt.request(url)
        if result.success:
            self.update_progress('status_getting_info', 100)
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]
        
        # Fallback to yt-dlp
        logger.info(f"[Instagram] Cobalt failed ({result.error}), trying yt-dlp")
        try:
            def extract():
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)
            
            info = await asyncio.to_thread(extract)
            self.update_progress('status_getting_info', 100)
            
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]
            
        except Exception as e:
            logger.error(f"[Instagram] Format error: {e}")
            # Even if format extraction fails, we can try downloading
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video - Cobalt first, yt-dlp fallback"""
        shortcode = self._extract_shortcode(url) or 'video'
        logger.info(f"[Instagram] Downloading: {shortcode}")
        
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)
        
        # === Try Cobalt ===
        self.update_progress('status_downloading', 10)
        filename, file_path = await cobalt.download(
            url, 
            download_dir,
            progress_callback=self.update_progress
        )
        
        # Get basic info for title if possible
        video_title = "Video"
        try:
            def get_info():
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    return ydl.extract_info(url, download=False)
            info = await asyncio.to_thread(get_info)
            video_title = info.get('title') or info.get('description') or "Video"
        except:
            pass

        # Safety: Truncate title for Telegram limits
        if len(video_title) > 800:
            video_title = video_title[:797] + "..."

        caption = (
            f"🎬 <b>{video_title}</b>\n\n"
            f"⚡ Instagram\n\n"
            f"<a href=\"{url}\">✨ Video Link</a>\n\n"
            f"📥 Downloaded via: @Tik_TokDownloader_Bot"
        )
        
        if file_path and file_path.exists():
            return caption, file_path
        
        # === Fallback to yt-dlp ===
        logger.info("[Instagram] Cobalt failed, trying yt-dlp")
        self.update_progress('status_downloading', 30)
        
        try:
            ydl_opts = self.ydl_opts.copy()
            ydl_opts['outtmpl'] = str(download_dir / f"instagram_{shortcode}.%(ext)s")
            
            def download_video():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=True)
            
            info = await asyncio.to_thread(download_video)
            
            if not info:
                raise DownloadError("Failed to download video")
            
            # Extract title from fallback info
            fallback_title = info.get('title') or info.get('description') or "Video"
            if len(fallback_title) > 800:
                fallback_title = fallback_title[:797] + "..."
            
            fallback_caption = (
                f"🎬 <b>{fallback_title}</b>\n\n"
                f"⚡ Instagram\n\n"
                f"<a href=\"{url}\">✨ Video Link</a>\n\n"
                f"📥 Downloaded via: @Tik_TokDownloader_Bot"
            )

            # Find file
            file_path = download_dir / f"instagram_{shortcode}.mp4"
            if not file_path.exists():
                for f in download_dir.glob(f"instagram_{shortcode}.*"):
                    file_path = f
                    break
            
            if not file_path.exists():
                 raise DownloadError("File downloaded but not found")

            return fallback_caption, file_path
            
        except Exception as e:
            logger.error(f"[Instagram] Download failed: {e}")
            raise DownloadError(f"Ошибка загрузки: {str(e)}")
