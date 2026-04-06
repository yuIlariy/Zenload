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
    # Added .m4a specifically for Spotify/High-quality audio
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
        self._update_interval = 3.0
        self._start_time = None

    def build_progress_bar(self, percent: int, length: int = 12) -> str:
        filled = int(length * percent / 100)
        return "█" * filled + "░" * (length - filled)

    def format_progress(self, prefix: str, current: int, total: int) -> str:
        """Calculates and formats speed and ETA"""
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
            if time.time() - self._last_update_time < self._update_interval:
                return
            self._last_update_time = time.time()
            await self._current_message.edit_text(text, parse_mode='HTML')
        except:
            pass

    async def upload_progress(self, current, total, *args):
        """Callback for Pyrogram uploads"""
        try:
            text = self.format_progress("⬆️ Uploading...", current, total)
            await self.update_message(text)
        except:
            pass

    async def _download_progress(self, status: str, progress: Any):
        """Standardized progress callback for both sync and async downloaders"""
        if not self._start_time:
            self._start_time = time.time()

        # Handle both percentage (int) and detailed data (dict)
        if isinstance(progress, dict):
            current = progress.get('downloaded_bytes', 0)
            total = progress.get('total_bytes', 0) or progress.get('total_bytes_estimate', 0)
            if total > 0:
                text = self.format_progress("⬇️ Downloading...", current, total)
            else:
                text = f"⬇️ Downloading...\n{status}"
        else:
            text = f"⬇️ Downloading...\n{self.build_progress_bar(progress)} {progress}%"
            
        await self.update_message(text)

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
            self._start_time = time.time() # Start timer for speed calc

            # ✅ Detect async vs sync downloader (Supports Spotify, TikTok, Instagram)
            download_func = downloader.download

            if inspect.iscoroutinefunction(download_func):
                metadata, file_path = await download_func(url, format_id)
            else:
                loop = asyncio.get_running_loop()
                metadata, file_path = await loop.run_in_executor(
                    None,
                    lambda: download_func(url, format_id)
                )

            if not file_path or not Path(file_path).exists():
                raise Exception("File not found after download task.")

            # ---- Metadata Trimming for Telegram Limits ----
            if metadata:
                if len(metadata) > 900:
                    metadata = metadata[:897] + "..."

            file_path_obj = Path(file_path)
            file_size = file_path_obj.stat().st_size
            chat_id = update.effective_chat.id

            # Reset timer for accurate upload speed
            self._start_time = time.time()

            # Spotify/M4A detection logic
            is_audio = (
                format_id == "audio" or 
                downloader.platform_id() == 'spotify' or
                file_path_obj.suffix.lower() in self.AUDIO_EXTENSIONS
            )

            # ---- UPLOAD LOGIC ----
            if file_size < 50 * 1024 * 1024:
                await self.update_message("⬆️ Uploading to Telegram...")

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
                await self.update_message("⬆️ Preparing large upload...")

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
                            timeout=900 # Increased timeout for large M4A/Videos
                        )
                    else:
                        sent_media = await asyncio.wait_for(
                            self.pyro_client.send_video(
                                chat_id=chat_id,
                                audio=str(file_path),
                                caption=metadata,
                                supports_streaming=True,
                                progress=self.upload_progress,
                                parse_mode=PyroParseMode.HTML
                            ),
                            timeout=900
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
            await update.effective_message.reply_text(f"❌ Download failed: {str(e)}")

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
                try: Path(file_path).unlink()
                except: pass
            try: await status_message.delete()
            except: pass


class DownloadManager:
    """Manages download sessions with a concurrency semaphore"""

    def __init__(self, localization, settings_manager,
                 max_concurrent_downloads=10, activity_logger=None):

        self.localization = localization
        self.settings_manager = settings_manager
        self.session = None
        self.activity_logger = activity_logger
        self.pyro_client = None

        # ✅ Prevent server overload
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
