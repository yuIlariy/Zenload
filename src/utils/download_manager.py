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

    # 🔥 Speed + ETA
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

    async def upload_progress(self, current, total):
        text = self.format_progress("⬆️ Uploading...", current, total)
        await self.update_message(text)

    async def process_download(self, downloader, url: str, update: Update, status_message: Message, format_id: str = None):
        user_id = update.effective_user.id
        file_path = None

        try:
            self._current_message = status_message
            self._current_user_id = user_id
            self._start_time = time.time()

            downloader.set_progress_callback(self._download_progress)

            await self.update_message("⬇️ Starting download...")

            metadata, file_path = await downloader.download(url, format_id)

            await self.update_message("⬆️ Preparing upload...")

            file_size = Path(file_path).stat().st_size
            chat_id = update.effective_chat.id

            # SMALL FILE → Bot API
            if file_size < 50 * 1024 * 1024:
                with open(file_path, 'rb') as file:
                    if file_path.suffix.lower() in ['.mp3', '.m4a', '.wav', '.ogg']:
                        await update.effective_message.reply_audio(audio=file, caption=metadata)
                    else:
                        await update.effective_message.reply_video(video=file, caption=metadata, supports_streaming=True)

            # LARGE FILE → Pyrogram
            else:
                async with UPLOAD_LIMIT:
                    if file_path.suffix.lower() in ['.mp3', '.m4a', '.wav', '.ogg']:
                        await pyro_app.send_audio(
                            chat_id=chat_id,
                            audio=str(file_path),
                            caption=metadata,
                            progress=self.upload_progress
                        )
                    else:
                        await pyro_app.send_video(
                            chat_id=chat_id,
                            video=str(file_path),
                            caption=metadata,
                            supports_streaming=True,
                            progress=self.upload_progress
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
        self.connector = None
        self.session = None
        self._loop = None
        self.active_downloads: Dict[int, Dict[str, asyncio.Task]] = defaultdict(dict)
        self._downloads_lock = None
        self.download_queue = None
        self._queue_processor_task = None
        self._queue_processor_running = False

    async def _create_queue(self):
        self.download_queue = asyncio.PriorityQueue()

    async def _ensure_initialized(self):
        if not self.session or self.session.closed:
            self.connector = aiohttp.TCPConnector(limit=self.max_concurrent_downloads, ssl=False)
            self.session = aiohttp.ClientSession(connector=self.connector)
            self._downloads_lock = asyncio.Lock()
            await self._create_queue()
            self._queue_processor_running = True
            self._queue_processor_task = asyncio.create_task(self._process_queue())

    async def _process_queue(self):
        while self._queue_processor_running:
            try:
                _, worker, args = await self.download_queue.get()
                await worker.process_download(*args)
                self.download_queue.task_done()
            except Exception as e:
                logger.error(f"Queue error: {e}")

    async def process_download(self, downloader, url, update, status_message, format_id=None):
        await self._ensure_initialized()

        user_id = update.effective_user.id

        async with self._downloads_lock:
            worker = DownloadWorker(self.localization, self.settings_manager, self.session, self.activity_logger)
            await self.download_queue.put((0, worker, (downloader, url, update, status_message, format_id)))

    async def cleanup(self):
        if self.session:
            await self.session.close()
