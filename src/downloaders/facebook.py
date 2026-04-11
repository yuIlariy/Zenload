import logging
import asyncio
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
import yt_dlp
from urllib.parse import urlparse
from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)

class FacebookDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        # Facebook sometimes requires cookies for private or age-restricted videos
        self.cookie_file = Path(__file__).parent.parent.parent / "cookies" / "facebook.txt"

    def platform_id(self) -> str:
        return 'facebook'

    def can_handle(self, url: str) -> bool:
        """Check if URL is from Facebook or FB Watch"""
        parsed = urlparse(url)
        return bool(parsed.netloc and any(domain in parsed.netloc.lower() for domain in ['facebook.com', 'fb.watch', 'web.facebook.com']))

    async def get_formats(self, url: str) -> List[Dict]:
        """Extract available FB formats using a high-compatibility profile"""
        try:
            self.update_progress('status_getting_info', 0)
            
            fb_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best', # Use 'best' to avoid specific stream availability issues
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                }
            }
            
            if self.cookie_file.exists():
                fb_opts['cookiefile'] = str(self.cookie_file)

            with yt_dlp.YoutubeDL(fb_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, str(url), download=False)
                
                formats = []
                if info and 'formats' in info:
                    seen = set()
                    for f in info['formats']:
                        # Facebook often provides 'hd' and 'sd' labels instead of heights
                        height = f.get('height')
                        if height:
                            quality = f"{height}p"
                            if quality not in seen:
                                formats.append({
                                    'id': f['format_id'],
                                    'quality': quality,
                                    'ext': f.get('ext', 'mp4')
                                })
                                seen.add(quality)
                
                # Sort by quality (highest first)
                return sorted(formats, key=lambda x: int(x['quality'][:-1]) if x['quality'][:-1].isdigit() else 0, reverse=True)

        except Exception as e:
            logger.error(f"[Facebook] Info extraction failed: {e}")
            raise DownloadError(f"Facebook extraction error: {str(e)}")

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download the selected Facebook video"""
        try:
            self.update_progress('status_downloading', 0)
            download_dir = (Path(__file__).parent.parent.parent / "downloads").resolve()
            download_dir.mkdir(exist_ok=True)

            ydl_opts = {
                'format': f"{format_id}/best" if format_id else "best",
                'outtmpl': str(download_dir / 'fb_%(id)s.%(ext)s'),
                'merge_output_format': 'mp4',
                'progress_hooks': [self._progress_hook],
            }

            if self.cookie_file.exists():
                ydl_opts['cookiefile'] = str(self.cookie_file)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, str(url), download=True)
                file_path = Path(ydl.prepare_filename(info)).resolve()
                
                return self._prepare_metadata(info), file_path

        except Exception as e:
            logger.error(f"[Facebook] Download failed: {e}")
            raise DownloadError(f"Facebook download failed: {str(e)}")

    def _prepare_metadata(self, info: Dict) -> str:
        """Format metadata for the Telegram response"""
        title = info.get('title', 'Facebook Video')
        uploader = info.get('uploader', 'Unknown User')
        return f"🎬 {title}\n\n👤 By: {uploader}\n\n📥 Downloader: @Tik_TokDownloader_Bot"
