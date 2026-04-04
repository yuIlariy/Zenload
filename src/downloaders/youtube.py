import re
import os
import logging
import asyncio
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
import yt_dlp
from urllib.parse import urlparse, parse_qs
from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)

class YouTubeDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        self.cookie_file = Path(__file__).parent.parent.parent / "cookies" / "youtube.txt"

    def platform_id(self) -> str:
        """Return platform identifier"""
        return 'youtube'

    def can_handle(self, url: str) -> bool:
        """Check if URL is from YouTube"""
        parsed = urlparse(url)
        return bool(
            parsed.netloc and any(domain in parsed.netloc.lower() 
            for domain in ['youtube.com', 'www.youtube.com', 'youtu.be'])
        )

    def preprocess_url(self, url: str) -> str:
        """Clean and validate YouTube URL"""
        parsed = urlparse(url)

        # Handle youtu.be URLs
        if 'youtu.be' in parsed.netloc:
            video_id = parsed.path.lstrip('/')
            return f'https://www.youtube.com/watch?v={video_id}'

        # Handle youtube.com URLs
        if 'youtube.com' in parsed.netloc:
            # Handle various YouTube URL formats
            if '/watch' in parsed.path:
                # Regular video URL
                return url
            elif '/shorts/' in parsed.path:
                # YouTube Shorts
                video_id = parsed.path.split('/shorts/')[1]
                return f'https://www.youtube.com/watch?v={video_id}'
            elif '/playlist' in parsed.path:
                # Return as is - yt-dlp handles playlists
                return url

        return url

    def _get_ydl_opts(self, format_id: Optional[str] = None) -> Dict:
        """Get yt-dlp options"""
        opts = {
            'format': format_id if format_id else 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
            'nooverwrites': True,
            'no_color': True,
            'no_warnings': True,
            'quiet': False,  # Show download progress
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
        """Get available formats for URL"""
        try:
            self.update_progress('status_getting_info', 0)
            processed_url = self.preprocess_url(url)
            logger.info(f"[YouTube] Getting formats for: {processed_url}")

            # Create download directory if not exists
            download_dir = Path(__file__).parent.parent.parent / "downloads"
            download_dir.mkdir(exist_ok=True)

            ydl_opts = self._get_ydl_opts()
            ydl_opts.update({
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

            raise DownloadError("Не удалось получить информацию о видео")

        except Exception as e:
            logger.error(f"[YouTube] Format extraction failed: {e}")
            if "Private video" in str(e):
                raise DownloadError("Это приватное видео")
            elif "Sign in" in str(e):
                raise DownloadError("Требуется авторизация")
            else:
                raise DownloadError(f"Ошибка при получении форматов: {str(e)}")

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video from URL"""
        try:
            self.update_progress('status_downloading', 0)
            processed_url = self.preprocess_url(url)
            logger.info(f"[YouTube] Downloading from: {processed_url}")

            # Create download directory if not exists
            download_dir = Path(__file__).parent.parent.parent / "downloads"
            download_dir.mkdir(exist_ok=True)
            download_dir = download_dir.resolve()  # Get absolute path
            logger.info(f"[YouTube] Download directory: {download_dir}")

            ydl_opts = self._get_ydl_opts(format_id)
            ydl_opts.update({
                'outtmpl': str(download_dir / '%(id)s.%(ext)s'),
            })

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.update_progress('status_downloading', 20)
                info = await asyncio.to_thread(
                    ydl.extract_info, str(processed_url), download=True
                )
                if info:
                    # Get downloaded file path and verify it exists
                    filename = ydl.prepare_filename(info)
                    file_path = Path(filename).resolve()
                    if file_path.exists():
                        logger.info("[YouTube] Download completed successfully")
                        return self._prepare_metadata(info, processed_url), file_path

            raise DownloadError("Не удалось загрузить видео")

        except Exception as e:
            error_msg = str(e)
            if "Private video" in error_msg:
                raise DownloadError("Это приватное видео")
            elif "Sign in" in error_msg:
                raise DownloadError("Требуется авторизация")
            else:
                logger.error(f"[YouTube] Download failed: {error_msg}")
                raise DownloadError(f"Ошибка загрузки: {error_msg}")

    def _prepare_metadata(self, info: Dict, url: str) -> str:
        """Prepare metadata string from info"""
        def format_number(num):
            if not num:
                return "0"
            if num >= 1000000:
                return f"{num/1000000:.1f}M"
            if num >= 1000:
                return f"{num/1000:.1f}K"
            return str(num)

        likes = format_number(info.get('like_count', 0))
        views = format_number(info.get('view_count', 0))
        channel = info.get('uploader', '')
        channel_url = info.get('uploader_url', url)

        return f"⚡YouTube | {views} | {likes}\n\n✨By <a href=\"{channel_url}\">{channel}</a>\n\n📥Downloaded via: @Tik_TokDownloader_Bot"

    def _progress_hook(self, d: Dict[str, Any]):
        """Progress hook for yt-dlp"""
        if d['status'] == 'downloading':
            # Get current event loop if available
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running() and not loop.is_closed():
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded = d.get('downloaded_bytes', 0)
                    if total > 0:
                        # Scale progress between 20-90% to leave room for pre/post processing
                        progress = int((downloaded / total) * 70) + 20
                        asyncio.create_task(
                            self.update_progress('status_downloading', progress)
                        )
            except Exception as e:
                if not "Event loop is closed" in str(e):
                    logger.error(f"Error in progress hook: {e}")


