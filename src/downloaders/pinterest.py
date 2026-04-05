"""Pinterest downloader - Cobalt primary, yt-dlp fallback"""

import logging
import asyncio
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import yt_dlp
from .base import BaseDownloader, DownloadError
from ..utils.cobalt_service import cobalt

logger = logging.getLogger(__name__)


class PinterestDownloader(BaseDownloader):
    """Pinterest downloader using Cobalt API with yt-dlp fallback"""
    
    def __init__(self):
        super().__init__()

    def platform_id(self) -> str:
        return 'pinterest'

    def can_handle(self, url: str) -> bool:
        return any(x in url.lower() for x in ['pinterest.com', 'pin.it'])

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats"""
        self.update_progress('status_getting_info', 0)
        
        # Try Cobalt
        result = await cobalt.request(url)
        if result.success:
            self.update_progress('status_getting_info', 100)
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]
        
        # Fallback to yt-dlp
        logger.info(f"[Pinterest] Cobalt failed ({result.error}), trying yt-dlp")
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True}
            
            def extract():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)
            
            info = await asyncio.to_thread(extract)
            self.update_progress('status_getting_info', 100)
            
            if info and 'formats' in info:
                formats = []
                for f in info['formats']:
                    if f.get('height'):
                        formats.append({'id': f['format_id'], 'quality': f"{f['height']}p", 'ext': 'mp4'})
                return sorted(formats, key=lambda x: int(x['quality'][:-1]), reverse=True) if formats else [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]
            
        except Exception as e:
            logger.warning(f"[Pinterest] yt-dlp format error: {e}")
        
        return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video - Cobalt first, yt-dlp fallback"""
        logger.info(f"[Pinterest] Downloading: {url}")
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)
        
        # Pre-fetch metadata for the caption
        title = "Pinterest Video"
        uploader = "Pinterest"
        
        try:
            def get_info():
                # We use a very basic options set here to just get info
                with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                    return ydl.extract_info(url, download=False)
            info = await asyncio.to_thread(get_info)
            title = info.get('title') or info.get('description') or "Pinterest Video"
            uploader = info.get('uploader') or info.get('channel') or "Pinterest"
        except:
            pass

        if len(title) > 800:
            title = title[:797] + "..."

        caption = (
            f"🎬 <b>{title}</b>\n\n"
            f"⚡ Pinterest\n"
            f"✨ By {uploader}\n\n"
            f"📥 Downloader: @Tik_TokDownloader_Bot"
        )

        # === Try Cobalt ===
        self.update_progress('status_downloading', 10)
        filename, file_path = await cobalt.download(
            url, 
            download_dir,
            progress_callback=self.update_progress
        )
        
        if file_path and file_path.exists():
            return caption, file_path
        
        # === Fallback to yt-dlp ===
        logger.info("[Pinterest] Cobalt failed, trying yt-dlp")
        self.update_progress('status_downloading', 30)
        
        try:
            # 🔥 FIX: We use 'best' as a fallback if the specific format_id fails
            # or if the user selected 'Best' from the menu.
            target_format = format_id if format_id and format_id != 'best' else 'best'
            
            ydl_opts = {
                'format': f'{target_format}/best', # Try target, then fallback to best
                'outtmpl': str(download_dir / '%(id)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
            }
            
            def download_video():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=True)
            
            info = await asyncio.to_thread(download_video)
            
            if info:
                # Prepare the final filename
                actual_filename = yt_dlp.YoutubeDL(ydl_opts).prepare_filename(info)
                file_path = Path(actual_filename).resolve()
                
                if file_path.exists():
                    return caption, file_path
            
            raise DownloadError("Failed to locate downloaded file")
            
        except Exception as e:
            logger.error(f"[Pinterest] Download failed: {e}")
            # If it still fails, one last attempt with absolute 'best'
            if 'format' in locals() and target_format != 'best':
                 return await self.download(url, format_id='best')
            raise DownloadError(f"Ошибка загрузки: {str(e)}")
