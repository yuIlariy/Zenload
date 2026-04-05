"""YouTube downloader with video + audio support (NO FFmpeg conversion)"""

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
            {'id': 'auto', 'quality': 'Best Video', 'ext': 'mp4'},
            {'id': 'audio', 'quality': 'Audio (Fast)', 'ext': 'm4a'},  # ✅ updated label
        ]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        try:
            processed_url = self.preprocess_url(url)

            download_dir = (Path(__file__).parent.parent.parent / "downloads").resolve()
            download_dir.mkdir(exist_ok=True)

            is_audio = format_id == "audio"

            loop = asyncio.get_running_loop()

            # ✅ THREAD-SAFE PROGRESS
            def progress_hook(d: Dict[str, Any]):
                if d['status'] == 'downloading':
                    try:
                        total = d.get('total_bytes') or d.get('total_bytes_estimate')
                        downloaded = d.get('downloaded_bytes', 0)

                        if total:
                            percent = int((downloaded / total) * 100)
                            asyncio.run_coroutine_threadsafe(
                                self.update_progress('status_downloading', percent),
                                loop
                            )
                    except Exception:
                        pass

            # ✅ BASE OPTIONS
            ydl_opts = {
                'outtmpl': str(download_dir / '%(id)s.%(ext)s'),
                'progress_hooks': [progress_hook],
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
            }

            # 🎵 AUDIO MODE (NO CONVERSION)
            if is_audio:
                ydl_opts.update({
                    'format': 'bestaudio[ext=m4a]/bestaudio',
                })
            else:
                ydl_opts.update({
                    'format': 'bv*+ba/best',
                    'merge_output_format': 'mp4',
                })

            # ✅ RUN yt-dlp IN THREAD (SAFE)
            def download_content():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(str(processed_url), download=True)
                    file_path = Path(ydl.prepare_filename(info)).resolve()

                    # Fix extension if needed
                    if is_audio:
                        alt = file_path.with_suffix(".m4a")
                    else:
                        alt = file_path.with_suffix(".mp4")

                    if not file_path.exists() and alt.exists():
                        file_path = alt

                    return info, file_path

            info, file_path = await asyncio.to_thread(download_content)

            if not file_path or not file_path.exists():
                raise DownloadError("Download failed.")

            return self._prepare_metadata(info, processed_url, is_audio), file_path

        except Exception as e:
            logger.error(f"[YouTube] Download failed: {e}")
            raise DownloadError(f"Download error: {str(e)}")

    def _prepare_metadata(self, info: Dict, url: str, is_audio: bool = False) -> str:
        title = info.get('title') or info.get('description') or "Video"
        views = info.get('view_count', 0)
        channel = info.get('uploader', 'Unknown')

        if len(title) > 800:
            title = title[:797] + "..."

        if is_audio:
            return (
                f"🎵 <b>{title}</b>\n\n"
                f"⚡ YouTube Audio (Fast)\n"
                f"✨ By {channel}\n\n"
                f"📥 Downloader: @Tik_TokDownloader_Bot"
            )

        return (
            f"🎬 <b>{title}</b>\n\n"
            f"⚡ YouTube | {views:,} Views\n"
            f"✨ By {channel}\n\n"
            f"📥 Downloader: @Tik_TokDownloader_Bot"
        )
