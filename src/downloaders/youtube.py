import re
import os
import logging
import asyncio
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
import yt_dlp
from urllib.parse import urlparse
from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)

class YouTubeDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        # Use absolute path for cookies to ensure they are found regardless of where the bot is run
        self.cookie_file = Path(__file__).parent.parent.parent / "cookies" / "youtube.txt"

    def platform_id(self) -> str:
        return 'youtube'

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(
            parsed.netloc and any(domain in parsed.netloc.lower() 
            for domain in ['youtube.com', 'www.youtube.com', 'youtu.be'])
        )

    def preprocess_url(self, url: str) -> str:
        parsed = urlparse(url)
        if 'youtu.be' in parsed.netloc:
            video_id = parsed.path.lstrip('/')
            return f'https://www.youtube.com/watch?v={video_id}'
        if 'youtube.com' in parsed.netloc:
            if '/shorts/' in parsed.path:
                video_id = parsed.path.split('/shorts/')[1]
                return f'https://www.youtube.com/watch?v={video_id}'
        return url

    def _get_ydl_opts(self, format_id: Optional[str] = None) -> Dict:
        """Get yt-dlp options with flexible format selection to prevent 'Format not available' errors"""
        # FIX: Use a more flexible format string by default to prevent crashes
        # This allows yt-dlp to pick the best available if the specific mp4+m4a combo isn't indexed
        default_format = 'bestvideo+bestaudio/best'
        
        opts = {
            'format': format_id if format_id else default_format,
            'merge_output_format': 'mp4',
            'nooverwrites': True,
            'no_color': True,
            'no_warnings': True,
            'quiet': False,
            'progress_hooks': [self._progress_hook],
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9'
            }
        }
        if self.cookie_file.exists():
            opts['cookiefile'] = str(self.cookie_file)
        return opts

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats for URL without strict format filtering"""
        try:
            self.update_progress('status_getting_info', 0)
            processed_url = self.preprocess_url(url)
            
            download_dir = Path(__file__).parent.parent.parent / "downloads"
            download_dir.mkdir(exist_ok=True)

            ydl_opts = self._get_ydl_opts()
            # FIX: Force 'best' during extraction to ensure we get the format list even if 
            # the default high-quality filter would otherwise fail
            ydl_opts.update({
                'format': 'best',
                'outtmpl': str(download_dir / '%(id)s.%(ext)s'),
            })

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(
                    ydl.extract_info, str(processed_url), download=False
                )
                if info and 'formats' in info:
                    formats = []
                    seen = set()
                    for f in info['formats']:
                        if not f.get('height'):
                            continue
                        quality = f"{f['height']}p"
                        if quality not in seen:
                            formats.append({
                                'id': f['format_id'],
                                'quality': quality,
                                'ext': f['ext']
                            })
                            seen.add(quality)
                    return sorted(formats, key=lambda x: int(x['quality'][:-1]), reverse=True)

            raise DownloadError("Failed to get video information")

        except Exception as e:
            logger.error(f"[YouTube] Format extraction failed: {e}")
            error_msg = str(e)
            if "Private video" in error_msg:
                raise DownloadError("This is a private video")
            elif "Sign in" in error_msg:
                raise DownloadError("Authentication required (update cookies)")
            else:
                raise DownloadError(f"Extraction error: {error_msg}")

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video from URL with automatic quality fallback"""
        try:
            self.update_progress('status_downloading', 0)
            processed_url = self.preprocess_url(url)

            download_dir = (Path(__file__).parent.parent.parent / "downloads").resolve()
            download_dir.mkdir(exist_ok=True)

            ydl_opts = self._get_ydl_opts(format_id)
            # FIX: Ensure a broad fallback if no specific format is selected
            if not format_id:
                ydl_opts['format'] = 'bestvideo+bestaudio/best'

            ydl_opts.update({
                'outtmpl': str(download_dir / '%(id)s.%(ext)s'),
            })

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.update_progress('status_downloading', 20)
                info = await asyncio.to_thread(
                    ydl.extract_info, str(processed_url), download=True
                )
                if info:
                    filename = ydl.prepare_filename(info)
                    file_path = Path(filename).resolve()
                    if file_path.exists():
                        return self._prepare_metadata(info, processed_url), file_path

            raise DownloadError("Download failed")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[YouTube] Download failed: {error_msg}")
            if "Private video" in error_msg:
                raise DownloadError("This is a private video")
            elif "Sign in" in error_msg:
                raise DownloadError("Authentication required (Check cookies)")
            else:
                raise DownloadError(f"Download error: {error_msg}")

    def _prepare_metadata(self, info: Dict, url: str) -> str:
        def format_number(num):
            if not num: return "0"
            if num >= 1000000: return f"{num/1000000:.1f}M"
            if num >= 1000: return f"{num/1000:.1f}K"
            return str(num)

        likes = format_number(info.get('like_count', 0))
        views = format_number(info.get('view_count', 0))
        channel = info.get('uploader', 'Unknown')
        channel_url = info.get('uploader_url', url)

        return f"⚡YouTube | {views} | {likes}\n\n✨By <a href=\"{channel_url}\">{channel}</a>\n\n📥Downloaded via: @Tik_TokDownloader_Bot"

    def _progress_hook(self, d: Dict[str, Any]):
        if d['status'] == 'downloading':
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running() and not loop.is_closed():
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded = d.get('downloaded_bytes', 0)
                    if total > 0:
                        progress = int((downloaded / total) * 70) + 20
                        asyncio.run_coroutine_threadsafe(
                            self.update_progress('status_downloading', progress),
                            loop
                        )
            except Exception:
                pass
