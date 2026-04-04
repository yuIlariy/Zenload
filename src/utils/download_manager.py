import logging
from pathlib import Path
from telegram import Update, Message
from telegram.error import BadRequest
from ..downloaders import DownloadError
import asyncio
import aiohttp
from typing import Dict, Optional
import time
from collections import defaultdict

from src.utils.pyro_client import app as pyro_app

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

UPLOAD_LIMIT = asyncio.Semaphore(3)


class DownloadWorker:
    auth_failure_tracker = defaultdict(int)
    ADMIN_ID = 6318135266

    def __init__(self, localization, settings_manager, session: aiohttp.ClientSession, activity_logger=None):
        self.localization = localization
        self.settings_manager = settings_manager
        self.session = session
        self.activity_logger = activity_logger

        self._current_message: Optional[Message] = None
        self._current_user_id: Optional[int] = None
        self._last_update_time = 0
        self._update_interval = 1.0
        self._start_time = None

    # 🔥 Progress bar
    def build_progress_bar(self, percent: int, length: int = 12) -> str:
        filled = int(length * percent / 100)
        return "█" * filled + "░" * (length - filled)

    # 🔥 Format progress
    def format_progress(self, prefix: str, current: int, total: int) -> str:
        percent = int((current / total) * 100) if total else 0
        bar = self.build_progress_bar(percent)

        elapsed = time.time() - self._start_time if self._start_time else 1
        speed = current / elapsed if elapsed > 0 else 0
        speed_mb = speed / (1024 * 1024)
        remaining = (total - current) / speed if speed > 0 else 0

        return (
            f"{prefix}\n"
            f"{bar} {percent}%\n"
            f"⚡ {speed_mb:.2f} MB/s | ⏳ {int(remaining)}s"
        )

    async def update_message(self, text: str):
        try:
            if time.time() - self._last_update_time < self._update_interval:
                return
            await self._current_message.edit_text(text)
            self._last_update_time = time.time()
        except:
            pass

    # 🔥 FIX: async upload progress
    async def upload_progress(self, current, total):
        text = self.format_progress("⬆️ Uploading...", current, total)
        await self.update_message(text)

    # 🔥 FIX: sync wrapper (CRITICAL)
    def upload_progress_sync(self, current, total):
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self.upload_progress(current, total))
        except:
            pass

    async def process_download(self, downloader, url: str, update: Update, status_message: Message, format_id: str = None):
        file_path = None

        try:
            self._current_message = status_message
            self._current_user_id = update.effective_user.id
            self._start_time = time.time()

            downloader.set_progress_callback(self._download_progress)

            await self.update_message("⬇️ Starting download...")

            metadata, file_path = await downloader.download(url, format_id)

            await self.update_message("⬆️ Preparing upload...")

            file_size = Path(file_path).stat().st_size
            chat_id = update.effective_chat.id

            # SMALL FILE
            if file_size < 50 * 1024 * 1024:
                with open(file_path, 'rb') as file:
                    await update.effective_message.reply_video(
                        video=file,
                        caption=metadata,
                        supports_streaming=True
                    )

            # LARGE FILE
            else:
                async with UPLOAD_LIMIT:
                    await pyro_app.send_video(
                        chat_id=chat_id,
                        video=str(file_path),
                        caption=metadata,
                        supports_streaming=True,
                        progress=self.upload_progress_sync  # 🔥 FIXED
                    )

            await self.update_message("✅ Done!")

        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            await update.effective_message.reply_text("❌ Download failed.")

        finally:
            if file_path:
                try:
                    Path(file_path).unlink()
                except:
                    pass

            try:
                await status_message.delete()
            except:
                pass

    async def _download_progress(self, status: str, progress: int):
        text = f"⬇️ Downloading...\n{self.build_progress_bar(progress)} {progress}%"
        await self.update_message(text)


class DownloadManager:
    def __init__(self, localization, settings_manager, max_concurrent_downloads=50, max_downloads_per_user=5, activity_logger=None):
        self.localization = localization
        self.settings_manager = settings_manager
        self.max_concurrent_downloads = max_concurrent_downloads
        self.max_downloads_per_user = max_downloads_per_user
        self.activity_logger = activity_logger
        self.session = None
        self._downloads_lock = asyncio.Lock()

    async def process_download(self, downloader, url, update, status_message, format_id=None):
        worker = DownloadWorker(self.localization, self.settings_manager, self.session, self.activity_logger)
        await worker.process_download(downloader, url, update, status_message, format_id)

    async def cleanup(self):
        if self.session:
            await self.session.close()
