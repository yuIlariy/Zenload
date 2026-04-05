import logging
from pathlib import Path
from telegram import Update, Message
import asyncio
import aiohttp
from typing import Optional
import time
from collections import defaultdict
import pyrogram

from pyrogram.enums import ParseMode as PyroParseMode

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class DownloadWorker:
    """Handles individual download and upload tasks with persistent stat tracking"""
    auth_failure_tracker = defaultdict(int)

    AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.opus', '.ogg', '.webm'}

    def __init__(self, localization, settings_manager, session: aiohttp.ClientSession,
                 activity_logger=None, pyro_client=None):
        self.localization = localization
        self.settings_manager = settings_manager
        self.session = session
        self.activity_logger = activity_logger
        self.pyro_client = pyro_client

        self._current_message: Optional[Message] = None
        self._current_user_id: Optional[int] = None
        self._last_update_time = 0
        self._update_interval = 3.0   # ✅ increased (less spam)
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
            self._last_update_time = time.time()
            await self._current_message.edit_text(text)
        except:
            pass

    async def upload_progress(self, current, total, *args):
        try:
            if current % (1024 * 1024 * 5) < 512 * 1024:
                logger.info(f"🚀 Uploading: {current/1024/1024:.1f}MB / {total/1024/1024:.1f}MB")

            text = self.format_progress("⬆️ Uploading...", current, total)
            await self.update_message(text)   # ✅ FIXED (no task spam)
        except:
            pass

    async def process_download(self, downloader, url: str, update: Update,
                               status_message: Message, format_id: str = None):

        file_path = None
        sent_media = None
        start_process_time = time.time()
        user_id = update.effective_user.id
        is_audio = False

        try:
            self._current_message = status_message
            self._current_user_id = user_id

            downloader.set_progress_callback(self._download_progress)

            await self.update_message("⬇️ Starting download...")

            # ✅ CRITICAL FIX: run blocking downloader in thread
            loop = asyncio.get_running_loop()
            metadata, file_path = await loop.run_in_executor(
                None,
                lambda: downloader.download(url, format_id)
            )

            # ---- metadata trim ----
            if metadata:
                parts = metadata.split('\n\n')
                if len(parts) >= 3:
                    footer = '\n\n'.join(parts[-2:])
                    header = '\n\n'.join(parts[:-2])
                    header_lines = header.split('\n')
                    if len(header_lines) > 3:
                        header = '\n'.join(header_lines[:3]) + "..."
                    if len(header) > 800:
                        header = header[:797] + "..."
                    metadata = f"{header}\n\n{footer}"
                elif len(metadata) > 900:
                    metadata = metadata[:897] + "..."

            file_path_obj = Path(file_path)
            file_size = file_path_obj.stat().st_size
            chat_id = update.effective_chat.id

            self._start_time = time.time()

            is_audio = (
                format_id == "audio" or
                file_path_obj.suffix.lower() in self.AUDIO_EXTENSIONS
            )

            # ---- SMALL FILE ----
            if file_size < 50 * 1024 * 1024:
                await self.update_message("⬆️ Uploading to Telegram...\n(Fast mode)")

                with open(file_path, 'rb') as file:
                    if is_audio:
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

            # ---- LARGE FILE ----
            else:
                await self.update_message("⬆️ Uploading large file...")
                logger.info(f"Pyrogram upload start | {file_size/1024/1024:.2f} MB")

                try:
                    if is_audio:
                        sent_media = await asyncio.wait_for(
                            self.pyro_client.send_audio(
                                chat_id=chat_id,
                                audio=str(file_path),
                                caption=metadata,
                                progress=self.upload_progress,
                                parse_mode=PyroParseMode.HTML
                            ),
                            timeout=600
                        )
                    else:
                        sent_media = await asyncio.wait_for(
                            self.pyro_client.send_video(
                                chat_id=chat_id,
                                video=str(file_path),
                                caption=metadata,
                                supports_streaming=True,
                                progress=self.upload_progress,
                                parse_mode=PyroParseMode.HTML
                            ),
                            timeout=600
                        )
                except asyncio.TimeoutError:
                    await self.update_message("❌ Upload timed out.")
                    return

            await self.update_message("✅ Done!")

            if self.activity_logger and sent_media:
                await self.activity_logger.log_media_transfer(
                    message=sent_media,
                    user_id=user_id,
                    url=url
                )

        except Exception as e:
            logger.error(f"Download error: {e}", exc_info=True)
            await update.effective_message.reply_text("❌ Download failed.")

        finally:
            if self.activity_logger:
                total_duration = time.time() - start_process_time
                actual_size = Path(file_path).stat().st_size if file_path and Path(file_path).exists() else 0

                await self.activity_logger.log_download_complete(
                    user_id=user_id,
                    url=url,
                    success=(sent_media is not None),
                    file_type="audio" if is_audio else "video",
                    file_size=actual_size,
                    processing_time=total_duration
                )

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
        await self.update_message(text)   # ✅ FIXED


class DownloadManager:
    """Manages download sessions and worker assignment"""

    def __init__(self, localization, settings_manager,
                 max_concurrent_downloads=10, activity_logger=None):

        self.localization = localization
        self.settings_manager = settings_manager
        self.session = None
        self.activity_logger = activity_logger
        self.pyro_client = None

        # ✅ NEW: concurrency limiter
        self.semaphore = asyncio.Semaphore(max_concurrent_downloads)

    async def process_download(self, downloader, url, update, status_message, format_id=None):

        async with self.semaphore:   # ✅ prevents overload
            worker = DownloadWorker(
                self.localization,
                self.settings_manager,
                self.session,
                self.activity_logger,
                self.pyro_client
            )
            await worker.process_download(downloader, url, update, status_message, format_id)

    async def cleanup(self):
        if self.session:
            await self.session.close()
