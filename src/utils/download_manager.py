import logging
from pathlib import Path
from telegram import Update, Message
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

    def __init__(self, localization, settings_manager, session: aiohttp.ClientSession, activity_logger=None):
        self.localization = localization
        self.settings_manager = settings_manager
        self.session = session
        # ✅ FIX: Actually save the logger so the worker can use it
        self.activity_logger = activity_logger 

        self._current_message: Optional[Message] = None
        self._current_user_id: Optional[int] = None
        self._last_update_time = 0
        self._update_interval = 1.0
        self._start_time = None

    def build_progress_bar(self, percent: int, length: int = 12) -> str:
        filled = int(length * percent / 100)
        return "█" * filled + "░" * (length - filled)

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

    def upload_progress_sync(self, current, total):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        try:
            asyncio.run_coroutine_threadsafe(
                self.upload_progress(current, total),
                loop
            )
        except:
            pass

    async def process_download(self, downloader, url: str, update: Update, status_message: Message, format_id: str = None):
        file_path = None
        sent_media = None # ✅ Track the message to forward to log channel

        try:
            self._current_message = status_message
            self._current_user_id = update.effective_user.id
            user_id = update.effective_user.id # For logging

            downloader.set_progress_callback(self._download_progress)

            await self.update_message("⬇️ Starting download...")

            metadata, file_path = await downloader.download(url, format_id)

            await self.update_message("⬆️ Preparing upload...")

            file_path_obj = Path(file_path)
            file_size = file_path_obj.stat().st_size
            chat_id = update.effective_chat.id

            self._start_time = time.time()

            # 🔥 SMALL FILE
            if file_size < 50 * 1024 * 1024:
                with open(file_path, 'rb') as file:
                    # ✅ Your requested logic for differentiating Audio/Video
                    if file_path_obj.suffix.lower() in ['.mp3', '.m4a', '.wav']:
                        sent_media = await update.effective_message.reply_audio(
                            audio=file, 
                            caption=metadata, 
                            parse_mode='HTML'
                        )
                    else:
                        sent_media = await update.effective_message.reply_video(
                            video=file, 
                            caption=metadata, 
                            parse_mode='HTML', 
                            supports_streaming=True
                        )

            # 🔥 LARGE FILE (Pyrogram)
            else:
                async with UPLOAD_LIMIT:
                    sent_media = await pyro_app.send_video(
                        chat_id=chat_id,
                        video=str(file_path),
                        caption=metadata,
                        supports_streaming=True,
                        progress=self.upload_progress_sync,
                        parse_mode="HTML"
                    )

            await self.update_message("✅ Done!")

            # 🔥 SEND TO LOGS CHANNEL
            if self.activity_logger and sent_media:
                await self.activity_logger.log_media_transfer(
                    message=sent_media,
                    user_id=user_id,
                    url=url
                )

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
        self.session = None
        self._downloads_lock = asyncio.Lock()
        # ✅ FIX: Actually save the logger to the manager
        self.activity_logger = activity_logger 

    async def process_download(self, downloader, url, update, status_message, format_id=None):
        # ✅ FIX: Pass the logger down to the worker
        worker = DownloadWorker(self.localization, self.settings_manager, self.session, self.activity_logger)
        await worker.process_download(downloader, url, update, status_message, format_id)

    async def cleanup(self):
        if self.session:
            await self.session.close()
