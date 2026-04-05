import logging
from pathlib import Path
from telegram import Update, Message
import asyncio
import aiohttp
from typing import Dict, Optional
import time
from collections import defaultdict
import pyrogram
from concurrent.futures import ThreadPoolExecutor # ✅ Required for non-blocking execution

from pyrogram.enums import ParseMode as PyroParseMode

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ✅ Global thread pool to handle CPU-intensive yt-dlp tasks
thread_executor = ThreadPoolExecutor(max_workers=10)

class DownloadWorker:
    """Handles individual download and upload tasks without blocking the event loop"""
    auth_failure_tracker = defaultdict(int)

    # ✅ Supported audio formats
    AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.opus', '.ogg', '.webm'}

    def __init__(self, localization, settings_manager, session: aiohttp.ClientSession, activity_logger=None, pyro_client=None):
        self.localization = localization
        self.settings_manager = settings_manager
        self.session = session
        self.activity_logger = activity_logger 
        self.pyro_client = pyro_client

        self._current_message: Optional[Message] = None
        self._current_user_id: Optional[int] = None
        self._last_update_time = 0
        self._update_interval = 2.0
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
        """Thread-safe message updates"""
        try:
            if time.time() - self._last_update_time < self._update_interval:
                return
            self._last_update_time = time.time()
            await self._current_message.edit_text(text)
        except:
            pass

    def sync_progress_hook(self, status: str, progress: int):
        """Hook called from background threads to update UI"""
        loop = asyncio.get_event_loop()
        text = f"⬇️ Downloading...\n{self.build_progress_bar(progress)} {progress}%"
        # Schedule the update back on the main event loop
        asyncio.run_coroutine_threadsafe(self.update_message(text), loop)

    async def upload_progress(self, current, total, *args):
        try:
            if current % (1024 * 1024 * 5) < 512 * 1024:
                logger.info(f"🚀 Uploading: {current/1024/1024:.1f}MB / {total/1024/1024:.1f}MB")

            text = self.format_progress("⬆️ Uploading...", current, total)
            asyncio.create_task(self.update_message(text))
        except Exception:
            pass

    async def process_download(self, downloader, url: str, update: Update, status_message: Message, format_id: str = None):
        file_path = None
        sent_media = None 
        start_process_time = time.time()
        user_id = update.effective_user.id
        is_audio = False
        loop = asyncio.get_running_loop()

        try:
            self._current_message = status_message
            self._current_user_id = user_id 

            # Use the thread-safe hook
            downloader.set_progress_callback(self.sync_progress_hook)

            await self.update_message("⬇️ Starting download...")

            # ✅ FIX: Run the blocking yt-dlp download in a separate thread
            metadata, file_path = await loop.run_in_executor(
                thread_executor, 
                lambda: downloader.download(url, format_id)
            )

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
                else:
                    if len(metadata) > 900:
                        metadata = metadata[:897] + "..."

            file_path_obj = Path(file_path)
            file_size = file_path_obj.stat().st_size
            chat_id = update.effective_chat.id

            self._start_time = time.time()

            is_audio = (
                format_id == "audio" or
                file_path_obj.suffix.lower() in self.AUDIO_EXTENSIONS
            )

            # 🔥 SMALL FILE (< 50MB)
            if file_size < 50 * 1024 * 1024:
                await self.update_message("⬆️ Uploading to Telegram...\n(Fast mode, please wait)")

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

            # 🔥 LARGE FILE (> 50MB) - Pyrogram
            else:
                await self.update_message("⬆️ Preparing large upload...")
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
                            timeout=900.0 # Increased timeout for large files
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
                            timeout=900.0
                        )
                except asyncio.TimeoutError:
                    logger.error("❌ Upload timed out")
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
        """Fallback for non-blocking status updates"""
        text = f"⬇️ Downloading...\n{self.build_progress_bar(progress)} {progress}%"
        asyncio.create_task(self.update_message(text))


class DownloadManager:
    """Manages download sessions and worker assignment"""
    def __init__(self, localization, settings_manager, max_concurrent_downloads=50, max_downloads_per_user=5, activity_logger=None):
        self.localization = localization
        self.settings_manager = settings_manager
        self.session = None
        self.activity_logger = activity_logger 
        self.pyro_client = None

    async def process_download(self, downloader, url, update, status_message, format_id=None):
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
