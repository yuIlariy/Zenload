"""Spotify downloader using spotDL for native m4a audio"""

import logging
import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse

from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)

class SpotifyDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        # ✅ VIRTUAL ENV FIX: Locate spotdl inside the venv bin folder
        self.spotdl_path = self._find_spotdl()
        self.ffmpeg_path = shutil.which("ffmpeg")
        
        if not self.spotdl_path:
            logger.error("[Spotify] spotdl binary not found in venv. Run 'pip install spotdl'")
        if not self.ffmpeg_path:
            logger.warning("[Spotify] ffmpeg not found globally. Metadata embedding may fail")

    def _find_spotdl(self) -> Optional[str]:
        """Ensures we use the spotdl installed in the virtual environment"""
        # First check the current Python's bin directory
        venv_bin = Path(sys.executable).parent
        spotdl_bin = venv_bin / "spotdl"
        if spotdl_bin.exists():
            return str(spotdl_bin)
        return shutil.which("spotdl")

    def platform_id(self) -> str:
        return 'spotify'

    def can_handle(self, url: str) -> bool:
        """Check for Spotify links, including short and desktop variants"""
        parsed = urlparse(url)
        return bool(
            parsed.netloc and 
            any(domain in parsed.netloc.lower() for domain in ['spotify.com', 'open.spotify.com'])
        )

    async def get_formats(self, url: str) -> List[Dict]:
        return [{'id': 'm4a', 'quality': 'High Quality (M4A)', 'ext': 'm4a'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download track as native m4a using spotDL subprocess"""
        logger.info(f"[Spotify] Processing: {url}")
        
        if not self.spotdl_path:
            raise DownloadError("spotdl not found. Ensure it is installed in your virtual env")

        download_dir = (Path(__file__).parent.parent.parent / "downloads").resolve()
        download_dir.mkdir(exist_ok=True)
        
        task_id = os.urandom(4).hex()
        temp_dir = download_dir / f"spot_{task_id}"
        temp_dir.mkdir(exist_ok=True)

        try:
            self.update_progress('status_downloading', 10)

            # ✅ THE FIX: Use 'download' command correctly with absolute paths
            # Removed --no-check-certificate as it caused 'unrecognized arguments'
            cmd = [
                self.spotdl_path, 
                "download", url,
                "--output", str(temp_dir),
                "--format", "m4a",
                "--bitrate", "disable",
                "--log-level", "INFO"
            ]

            # ✅ RUN SUBPROCESS
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Ensure the subprocess can find global tools like ffmpeg
                env=os.environ.copy() 
            )

            try:
                # 5-minute timeout to prevent hanging the bot
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
            except asyncio.TimeoutError:
                process.kill()
                raise DownloadError("Download timed out (5 min limit)")

            if process.returncode != 0:
                err = stderr.decode().strip()
                logger.error(f"[Spotify] spotDL error: {err}")
                raise DownloadError(f"SpotDL failed: {err[:100]}")

            # ✅ FIND AND MOVE FILE
            files = list(temp_dir.glob("*.m4a"))
            if not files:
                # Fallback check for any audio file
                files = list(temp_dir.glob("*.*"))
                if not files:
                    raise DownloadError("No file found after spotDL finished")

            file_path = files[0]
            track_title = file_path.stem
            final_path = download_dir / f"{track_title}_{task_id}{file_path.suffix}"
            
            shutil.move(str(file_path), str(final_path))
            
            metadata = self._prepare_metadata(url, track_title)
            return metadata, final_path

        except Exception as e:
            logger.error(f"[Spotify] Download failed: {e}")
            raise DownloadError(f"Spotify error: {str(e)}")
        
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

    def _prepare_metadata(self, url: str, title: str) -> str:
        """Standardized Spotify caption"""
        return (
            f"🎵 <b>{title}</b>\n\n"
            f"⚡ <b>Platform:</b> Spotify (Native M4A)\n"
            f"🔗 <a href='{url}'>View on Spotify</a>\n\n"
            f"📥 <b>@Tik_TokDownloader_Bot</b>"
        )
