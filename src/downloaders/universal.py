"""Universal catch-all downloader using yt-dlp (No FFmpeg conversion)"""

import logging
import asyncio
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
import yt_dlp
from urllib.parse import urlparse
from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)

class UniversalDownloader(BaseDownloader):
    def platform_id(self) -> str:
        return 'universal'

    def can_handle(self, url: str) -> bool:
        # Catches any valid HTTP/HTTPS link.
        # MUST BE THE LAST DOWNLOADER IN THE LIST!
        parsed = urlparse(url)
        return parsed.scheme in ('http', 'https')

    async def get_formats(self, url: str) -> List[Dict]:
        return [
            {'id': 'video', 'quality': 'Best Available Video', 'ext': 'mp4'},
            # Changed to Native Audio so it doesn't promise MP3
            {'id': 'audio', 'quality': 'Native Audio (Fast)', 'ext': 'm4a'}, 
        ]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        try:
            download_dir = (Path(__file__).parent.parent.parent / "downloads").resolve()
            download_dir.mkdir(exist_ok=True)

            is_audio = format_id == "audio"
            loop = asyncio.get_running_loop()

            # Thread-safe progress bar
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

            ydl_opts = {
                'outtmpl': str(download_dir / 'universal_%(extractor)s_%(id)s.%(ext)s'),
                'progress_hooks': [progress_hook],
                'quiet': True,
                'no_warnings': True,
            }

            # 🚫 NO FFMPEG POST-PROCESSORS HERE
            if is_audio:
                ydl_opts.update({
                    # Try to get m4a first since it plays everywhere, otherwise just grab the best audio
                    'format': 'bestaudio[ext=m4a]/bestaudio/best',
                })
            else:
                ydl_opts.update({
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'merge_output_format': 'mp4',
                })

            def run_ytdlp():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    
                    # Let yt-dlp tell us what the final file actually is
                    # No forcing extensions!
                    file_path = Path(ydl.prepare_filename(info))
                        
                    return info, file_path

            info, file_path = await asyncio.to_thread(run_ytdlp)

            if not file_path or not file_path.exists():
                raise DownloadError("Download failed. The site might be unsupported or rate-limiting.")

            title = info.get('title') or info.get('description') or "Media Download"
            extractor = info.get('extractor_key', 'Universal')
            
            if len(title) > 800:
                title = title[:797] + "..."

            caption = (
                f"🔗 <b>{title}</b>\n\n"
                f"⚡ <b>Source:</b> {extractor}\n"
                f"📥 <b>@Tik_TokDownloader_Bot</b>"
            )

            return caption, file_path

        except Exception as e:
            logger.error(f"[Universal] Error: {e}")
            raise DownloadError(f"Site unsupported or media protected. Error: {str(e)}")
