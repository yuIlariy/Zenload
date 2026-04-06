"""Spotify downloader using spotDL for native m4a audio"""

import logging
import asyncio
import os
import shutil
import sys
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse

from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)

class SpotifyDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        # ✅ VIRTUAL ENV FIX: Find the absolute path for spotdl
        self.spotdl_path = self._find_spotdl()
        self.ffmpeg_path = shutil.which("ffmpeg")
        
        if not self.spotdl_path:
            logger.error("[Spotify] spotdl binary not found!")

    def _find_spotdl(self) -> Optional[str]:
        """Locates the spotdl binary relative to the virtual env"""
        python_bin_dir = Path(sys.executable).parent
        env_spotdl = python_bin_dir / "spotdl"
        if env_spotdl.exists():
            return str(env_spotdl)
        return shutil.which("spotdl")

    def platform_id(self) -> str:
        return 'spotify'

    def can_handle(self, url: str) -> bool:
        """Check if the URL is a valid Spotify link"""
        parsed = urlparse(url)
        return bool(
            parsed.netloc and 
            any(domain in parsed.netloc.lower() for domain in ['spotify.com', 'open.spotify.com'])
        )

    async def get_formats(self, url: str) -> List[Dict]:
        return [{'id': 'm4a', 'quality': 'High Quality (M4A)', 'ext': 'm4a'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download track as native m4a without freezing the bot"""
        logger.info(f"[Spotify] Processing: {url}")
        
        if not self.spotdl_path:
            raise DownloadError("spotdl binary not found.")

        download_dir = (Path(__file__).parent.parent.parent / "downloads").resolve()
        download_dir.mkdir(exist_ok=True)
        
        task_id = os.urandom(4).hex()
        temp_dir = download_dir / f"spot_{task_id}"
        temp_dir.mkdir(exist_ok=True)

        # ✅ THE FIX: Wrap the blocking subprocess in a thread
        def run_spotdl():
            cmd = [
                self.spotdl_path, 
                "download", url,
                "--output", str(temp_dir),
                "--format", "m4a",
                "--bitrate", "disable",
                "--log-level", "ERROR"
            ]
            
            # Using synchronous subprocess inside the thread
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True,
                env=os.environ.copy()
            )
            return result

        try:
            self.update_progress('status_downloading', 20)

            # Move the CPU-heavy work to a thread so the bot stays alive
            result = await asyncio.to_thread(run_spotdl)

            if result.returncode != 0:
                logger.error(f"[Spotify] spotDL error: {result.stderr}")
                raise DownloadError(f"SpotDL failed: {result.stderr[:100]}")

            # Find the downloaded file
            files = list(temp_dir.glob("*.m4a"))
            if not files:
                files = list(temp_dir.glob("*.*"))
                if not files:
                    raise DownloadError("Audio file not found after download")

            file_path = files[0]
            track_title = file_path.stem
            
            final_path = download_dir / f"{track_title}_{task_id}{file_path.suffix}"
            shutil.move(str(file_path), str(final_path))
            
            caption = (
                f"🎵 <b>{track_title}</b>\n\n"
                f"⚡ <b>Platform:</b> Spotify (Native M4A)\n"
                f"🔗 <a href='{url}'>View on Spotify</a>\n\n"
                f"📥 <b>@Tik_TokDownloader_Bot</b>"
            )
            return caption, final_path

        except Exception as e:
            logger.error(f"[Spotify] Download failed: {e}")
            raise DownloadError(f"Spotify error: {str(e)}")
        
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
