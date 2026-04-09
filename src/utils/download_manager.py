import logging
from pathlib import Path
from telegram import Update, Message
import asyncio
import aiohttp
from typing import Optional, Any
import time
from collections import defaultdict
import inspect
import pyrogram

from pyrogram.enums import ParseMode as PyroParseMode

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class DownloadWorker:
    """Handles individual download and upload tasks"""

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
        self._update_interval = 4.0
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
            f"<b>{prefix}</b>\n"
            f"<code>{bar}</code> {percent}%\n"
            f"⚡ {speed_mb:.2f} MB/s | ⏳ {int(remaining)}s"
        )

    async def update_message(self, text: str):
        try:
            now = time.time()
            if now - self._last_update_time < self._update_interval:
                return
            
            self._last_update_time = now
            await self._current_message.edit_text(text, parse_mode='HTML')
        except Exception:
            pass

    async def upload_progress(self, current, total, *args):
        try:
            text = self.format_progress("⬆️ Uploading...", current, total)
            await self.update_message(text)
        except Exception:
            pass

    async def _download_progress(self, status: str, progress: Any):
        if not self._start_time:
            self._start_time = time.time()

        try:
            if isinstance(progress, dict):
                current = progress.get('downloaded_bytes', 0)
                total = progress.get('total_bytes', 0) or progress.get('total_bytes_estimate', 0)

                if total > 0:
                    text = self.format_progress("⬇️ Downloading...", current, total)
                else:
                    text = f"⬇️ Downloading...\n<i>{status}</i>"
            else:
                text = f"⬇️ Downloading...\n{self.build_progress_bar(progress)} {progress}%"

            await self.update_message(text)
        except Exception:
            pass

    async def process_download(self, downloader, url: str, update: Update,
                               status_message: Message, format_id: str = None):

        file_path = None
        sent_media = None
        is_audio = False
        error_msg = None

        try:
            self._current_message = status_message
            downloader.set_progress_callback(self._download_progress)
            self._start_time = time.time()

            await self.update_message("⬇️ <b>Processing...</b>")

            metadata, file_path = await downloader.download(url, format_id)

            if not file_path or not Path(file_path).exists():
                raise Exception("File was not found after download completion.")

            if metadata and len(metadata) > 900:
                metadata = metadata[:897] + "..."

            file_path_obj = Path(file_path)
            file_size = file_path_obj.stat().st_size
            chat_id = update.effective_chat.id

            # Reset timer for upload tracking
            self._start_time = time.time()

            is_audio = (
                format_id == "audio" or 
                downloader.platform_id() == 'spotify' or 
                file_path_obj.suffix.lower() in self.AUDIO_EXTENSIONS
            )

            # ---- UPLOAD ----
            if file_size < 50 * 1024 * 1024:
                await self.update_message("⬆️ <b>Uploading...</b>")

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
            else:
                await self.update_message("⬆️ <b>Uploading large file...</b>")

                try:
                    async with asyncio.timeout(1200):
                        if is_audio:
                            sent_media = await self.pyro_client.send_audio(
                                chat_id=chat_id,
                                audio=str(file_path),
                                caption=metadata,
                                progress=self.upload_progress,
                                parse_mode=PyroParseMode.HTML
                            )
                        else:
                            sent_media = await self.pyro_client.send_video(
                                chat_id=chat_id,
                                video=str(file_path),
                                caption=metadata,
                                supports_streaming=True,
                                progress=self.upload_progress,
                                parse_mode=PyroParseMode.HTML
                            )
                except asyncio.TimeoutError:
                    raise Exception("Upload timed out.")

            self._last_update_time = 0
            await self.update_message("✅ <b>Finished!</b>")

            # 🔥 AUTO LOGGER (SUCCESS)
            if self.activity_logger and sent_media:
                total_time = time.time() - self._start_time

                await self.activity_logger.log_media_transfer(
                    message=sent_media,
                    user_id=update.effective_user.id,
                    url=url,
                    success=True,
                    file_size=file_size,
                    processing_time=total_time
                )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Download manager error: {e}", exc_info=True)

            # 🔥 AUTO LOGGER (FAIL)
            if self.activity_logger:
                total_time = time.time() - self._start_time if self._start_time else 0

                await self.activity_logger.log_media_transfer(
                    message=update.effective_message,
                    user_id=update.effective_user.id,
                    url=url,
                    success=False,
                    file_size=None,
                    processing_time=total_time
                )

            try:
                await update.effective_message.reply_text(
                    f"❌ <b>Download failed:</b>\n<code>{str(e)}</code>",
                    parse_mode='HTML'
                )
            except:
                pass

        finally:
            # 1. Grab the file size BEFORE deleting it (for the logger)
            actual_size = 0
            if file_path and Path(file_path).exists():
                try:
                    actual_size = Path(file_path).stat().st_size
                except Exception:
                    pass

            # 2. DELETE THE FILE IMMEDIATELY (Priority #1 to save disk space)
            if file_path and Path(file_path).exists():
                try:
                    Path(file_path).unlink()
                    logger.info(f"🧹 Cleaned up file: {file_path}")
                except Exception as e:
                    logger.error(f"⚠️ Failed to delete file {file_path}: {e}")

            # 3. Safely log to database 
            if self.activity_logger:
                try:
                    total_duration = time.time() - self._start_time if self._start_time else 0
                    await self.activity_logger.log_download_complete(
                        user_id=update.effective_user.id,
                        url=url,
                        success=(sent_media is not None),
                        file_type="audio" if is_audio else "video",
                        file_size=actual_size,
                        processing_time=total_duration,
                        error=error_msg
                    )
                except Exception as e:
                    logger.error(f"Activity logger failed: {e}")
            
            # 4. Delete the "Processing..." message
            try:
                if status_message:
                    await status_message.delete()
            except:
                pass


class DownloadManager:

    def __init__(self, localization, settings_manager,
                 max_concurrent_downloads=3, activity_logger=None):

        self.localization = localization
        self.settings_manager = settings_manager
        self.session = None
        self.activity_logger = activity_logger
        self.pyro_client = None

        self.semaphore = asyncio.Semaphore(max_concurrent_downloads)

    async def process_download(self, downloader, url, update, status_message, format_id=None):
        async with self.semaphore:
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
