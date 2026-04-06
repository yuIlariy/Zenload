"""Spotify downloader using spotDL for native m4a audio"""

import logging
import asyncio
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse

from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)

class SpotifyDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        # Check if ffmpeg is available as it's required for spotDL
        self.ffmpeg_path = shutil.which("ffmpeg")
        if not self.ffmpeg_path:
            logger.error("[Spotify] ffmpeg not found! Downloads will fail.")

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
        """Spotify doesn't have multiple formats; we always aim for best M4A"""
        self.update_progress('status_getting_info', 100)
        return [{'id': 'm4a', 'quality': 'High Quality (M4A)', 'ext': 'm4a'}]

    def _build_caption(self, url: str, title: str) -> str:
        """Standardized caption for Spotify tracks"""
        return (
            f"🎵 <b>{title}</b>\n\n"
            f"⚡ <b>Platform:</b> Spotify\n"
            f"🔗 <a href='{url}'>View on Spotify</a>\n\n"
            f"📥 <b>@Tik_TokDownloader_Bot</b>"
        )

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download track as native m4a using spotDL"""
        logger.info(f"[Spotify] Processing: {url}")
        
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)
        
        # Unique ID for this task to prevent file collisions
        task_id = os.urandom(4).hex()
        temp_dir = download_dir / f"spot_{task_id}"
        temp_dir.mkdir(exist_ok=True)

        try:
            self.update_progress('status_downloading', 20)

            # ✅ THE FIX: Use spotDL to fetch native m4a
            # --format m4a: Ensures we get AAC/M4A
            # --bitrate disable: Prevents re-encoding/transcoding
            cmd = [
                "spotdl", "download", url,
                "--output", str(temp_dir),
                "--format", "m4a",
                "--bitrate", "disable",
                "--no-check-certificate"
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                logger.error(f"[Spotify] spotDL error: {error_msg}")
                raise DownloadError(f"SpotDL failed: {error_msg}")

            # Find the downloaded file
            files = list(temp_dir.glob("*.m4a"))
            if not files:
                raise DownloadError("Audio file not found after download.")

            file_path = files[0]
            track_title = file_path.stem.replace(".m4a", "")
            
            # Move file to main downloads folder and cleanup
            final_path = download_dir / f"{track_title}_{task_id}.m4a"
            shutil.move(str(file_path), str(final_path))
            
            caption = self._build_caption(url, track_title)
            return caption, final_path

        except Exception as e:
            logger.error(f"[Spotify] Download failed: {e}")
            raise DownloadError(f"Spotify error: {str(e)}")
        
        finally:
            # Cleanup temp directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
