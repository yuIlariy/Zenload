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

# 🔥 Pyrogram
from src.utils.pyro_client import app as pyro_app

# Configure logging
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# 🔥 Parallel uploads
UPLOAD_LIMIT = asyncio.Semaphore(3)


class DownloadWorker:
    auth_failure_tracker = defaultdict(int)
    ADMIN_ID = 6318135266

    def __init__(self, localization, settings_manager, session: aiohttp.ClientSession, activity_logger=None):
        self.localization = localization
        self.settings_manager = settings_manager
        self.session = session
        self.activity_logger = activity_logger
        self._status_queue = asyncio.Queue()
        self._stop_event = asyncio.Event()
        self._current_message: Optional[Message] = None
        self._current_user_id: Optional[int] = None
        self._last_status: Optional[str] = None
        self._last_progress: Optional[int] = None
        self._status_task: Optional[asyncio.Task] = None
        self._last_update_time = 0
        self._update_interval = 0.5

    async def get_message(self, user_id: int, key: str, **kwargs) -> str:
        settings = await self.settings_manager.get_settings(user_id)
        return self.localization.get(settings.language, key, **kwargs)

    async def update_status(self, message: Message, user_id: int, status_key: str, progress: int):
        try:
            current_time = time.time()
            if current_time - self._last_update_time < self._update_interval:
                return

            new_text = await self.get_message(user_id, status_key, progress=progress)

            if new_text == self._last_status and progress == self._last_progress:
                return

            await message.edit_text(new_text)
            self._last_status = new_text
            self._last_progress = progress
            self._last_update_time = current_time

        except Exception:
            pass

    async def _process_status_updates(self):
        try:
            while not self._stop_event.is_set():
                try:
                    status, progress = await asyncio.wait_for(self._status_queue.get(), timeout=0.1)
                    if status == "STOP":
                        break

                    if self._current_message:
                        await self.update_status(self._current_message, self._current_user_id, status, progress)
                        self._status_queue.task_done()

                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass

    async def progress_callback(self, status: str, progress: int):
        await self._status_queue.put((status, progress))

    async def process_download(self, downloader, url: str, update: Update, status_message: Message, format_id: str = None):
        user_id = update.effective_user.id
        file_path = None
        platform = downloader.__class__.__name__.lower().replace('downloader', '')

        try:
            self._current_message = status_message
            self._current_user_id = user_id
            self._stop_event.clear()
            self._status_task = asyncio.create_task(self._process_status_updates())

            downloader.set_progress_callback(self.progress_callback)

            await self.update_status(status_message, user_id, 'status_getting_info', 0)

            metadata, file_path = await downloader.download(url, format_id)

            await self.update_status(status_message, user_id, 'status_sending', 0)

            file_size = Path(file_path).stat().st_size
            chat_id = update.effective_chat.id

            # 🔥 SMALL FILE
            if file_size < 50 * 1024 * 1024:
                with open(file_path, 'rb') as file:
                    if file_path.suffix.lower() in ['.mp3', '.m4a', '.wav', '.ogg']:
                        await update.effective_message.reply_audio(audio=file, caption=metadata)
                    else:
                        await update.effective_message.reply_video(video=file, caption=metadata, supports_streaming=True)

            # 🚀 LARGE FILE (Pyrogram)
            else:
                async with UPLOAD_LIMIT:
                    if file_path.suffix.lower() in ['.mp3', '.m4a', '.wav', '.ogg']:
                        await pyro_app.send_audio(
                            chat_id=chat_id,
                            audio=str(file_path),
                            caption=metadata,
                            progress=lambda c, t: None
                        )
                    else:
                        await pyro_app.send_video(
                            chat_id=chat_id,
                            video=str(file_path),
                            caption=metadata,
                            supports_streaming=True,
                            progress=lambda c, t: None
                        )

            await self.update_status(status_message, user_id, 'status_sending', 100)

        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            await update.effective_message.reply_text("❌ Download failed.")

        finally:
            self._stop_event.set()

            if self._status_task:
                self._status_task.cancel()

            if file_path:
                try:
                    Path(file_path).unlink()
                except Exception:
                    pass

            try:
                await status_message.delete()
            except Exception:
                pass


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
