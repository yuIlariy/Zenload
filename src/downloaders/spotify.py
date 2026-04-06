"""Spotify downloader using spotDL for native m4a audio"""

import logging
import asyncio
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
from concurrent.futures import ProcessPoolExecutor

from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)

# 🔥 IMPORTANT: limit processes (prevents CPU overload)
executor = ProcessPoolExecutor(max_workers=2)


def run_spotdl_blocking(cmd):
    """Runs spotDL in a separate process (FULL isolation)"""
    import subprocess
    return subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


class SpotifyDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        self.spotdl_path = self._find_spotdl()
        self.ffmpeg_path = shutil.which("ffmpeg")

        if not self.spotdl_path:
            logger.error("[Spotify] spotdl binary not found!")

    def _find_spotdl(self) -> Optional[str]:
        python_bin_dir = Path(sys.executable).parent
        env_spotdl = python_bin_dir / "spotdl"
        if env_spotdl.exists():
            return str(env_spotdl)
        return shutil.which("spotdl")

    def platform_id(self) -> str:
        return 'spotify'

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(
            parsed.netloc and
            any(domain in parsed.netloc.lower() for domain in ['spotify.com', 'open.spotify.com'])
        )

    async def get_formats(self, url: str) -> List[Dict]:
        return [{'id': 'm4a', 'quality': 'High Quality (M4A)', 'ext': 'm4a'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        logger.info(f"[Spotify] Processing: {url}")

        if not self.spotdl_path:
            raise DownloadError("spotdl binary not found.")

        download_dir = (Path(__file__).parent.parent.parent / "downloads").resolve()
        download_dir.mkdir(exist_ok=True)

        task_id = os.urandom(4).hex()
        temp_dir = download_dir / f"spot_{task_id}"
        temp_dir.mkdir(exist_ok=True)

        cmd = [
            self.spotdl_path,
            "download",
            url,
            "--output", str(temp_dir),
            "--format", "m4a",
            "--bitrate", "disable",
            "--log-level", "ERROR"
        ]

        try:
            self.update_progress('status_downloading', 10)

            loop = asyncio.get_running_loop()

            # ✅ RUN IN SEPARATE PROCESS (NO FREEZE POSSIBLE)
            future = loop.run_in_executor(executor, run_spotdl_blocking, cmd)

            progress = 10
            start_time = time.time()
            timeout = 180  # 3 minutes safety

            # ✅ Non-blocking progress loop
            while not future.done():
                if time.time() - start_time > timeout:
                    logger.error("[Spotify] Timeout — killing task")
                    raise DownloadError("Spotify download timed out")

                if progress < 90:
                    progress += 1
                    self.update_progress('status_downloading', progress)

                await asyncio.sleep(1)

            result = await future

            if result.returncode != 0:
                raise DownloadError("SpotDL failed during execution")

            # ✅ Find downloaded file
            files = list(temp_dir.glob("*.m4a"))
            if not files:
                files = list(temp_dir.glob("*.*"))
                if not files:
                    raise DownloadError("Audio file not found after download")

            file_path = files[0]
            track_title = file_path.stem

            final_path = download_dir / f"{track_title}_{task_id}{file_path.suffix}"
            shutil.move(str(file_path), str(final_path))

            self.update_progress('status_downloading', 100)

            caption = (
                f"🎵 <b>{track_title}</b>\n\n"
                f"⚡ <b>Platform:</b> Spotify (Native M4A)\n"
                f"🔗 <a href='{url}'>Watch on Spotify</a>\n\n"
                f"📥 <b>@Tik_TokDownloader_Bot</b>"
            )

            return caption, final_path

        except Exception as e:
            logger.error(f"[Spotify] Download failed: {e}")
            raise DownloadError(f"Spotify error: {str(e)}")

        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
