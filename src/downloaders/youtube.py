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

    def platform_id(self) -> str:
        return 'youtube'

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(parsed.netloc and any(domain in parsed.netloc.lower() for domain in [
            'youtube.com', 'www.youtube.com', 'youtu.be'
        ]))

    def preprocess_url(self, url: str) -> str:
        parsed = urlparse(url)
        if 'youtu.be' in parsed.netloc:
            video_id = parsed.path.lstrip('/')
            return f'https://www.youtube.com/watch?v={video_id}'
        return url

    async def get_formats(self, url: str) -> List[Dict]:
        return [
            {'id': 'auto', 'quality': 'Best', 'ext': 'mp4'}
        ]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        try:
            processed_url = self.preprocess_url(url)

            download_dir = (Path(__file__).parent.parent.parent / "downloads").resolve()
            download_dir.mkdir(exist_ok=True)

            format_selector = "bv*+ba/best"
            
            # 🔥 FIX: Capture the main event loop safely to use inside the background thread
            loop = asyncio.get_running_loop()

            # 🔥 FIX: Thread-safe progress hook that prevents asyncio crashes
            def progress_hook(d: Dict[str, Any]):
                if d['status'] == 'downloading':
                    try:
                        total = d.get('total_bytes') or d.get('total_bytes_estimate')
                        downloaded = d.get('downloaded_bytes', 0)

                        if total:
                            percent = int((downloaded / total) * 100)
                            # Safely send the update back to the main bot loop
                            asyncio.run_coroutine_threadsafe(
                                self.update_progress('status_downloading', percent), 
                                loop
                            )
                    except Exception:
                        pass

            ydl_opts = {
                'format': format_selector,
                'merge_output_format': 'mp4',
                'outtmpl': str(download_dir / '%(id)s.%(ext)s'),
                'progress_hooks': [progress_hook],
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'format_sort': ['res', 'ext:mp4:m4a'],
            }

            def download_content():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(str(processed_url), download=True)

            info = await asyncio.to_thread(download_content)

            file_path = Path(yt_dlp.YoutubeDL(ydl_opts).prepare_filename(info)).resolve()

            if file_path.exists():
                return self._prepare_metadata(info, processed_url), file_path

            raise DownloadError("Download failed.")

        except Exception as e:
            logger.error(f"[YouTube] Download failed: {e}")
            raise DownloadError(f"Download error: {str(e)}")

    def _prepare_metadata(self, info: Dict, url: str) -> str:
        views = info.get('view_count', 0)
        channel = info.get('uploader', 'Unknown')

        return (
            f"⚡YouTube | {views:,} Views\n\n"
            f"✨By {channel}\n\n"
            f"📥Downloaded via: @Tik_TokDownloader_Bot"
        )
