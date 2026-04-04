import logging
from pathlib import Path
from telegram import Update, Message
import asyncio
import aiohttp
from typing import Dict, Optional
import time
from collections import defaultdict

from src.utils.pyro_client import app as pyro_app
from pyrogram.enums import ParseMode as PyroParseMode

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

class DownloadWorker:
    auth_failure_tracker = defaultdict(int)

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

    async def upload_progress(self, current, total, *args):
        text = self.format_progress("⬆️ Uploading (Pyrogram)...", current, total)
        await self.update_message(text)

    async def process_download(self, downloader, url: str, update: Update, status_message: Message, format_id: str = None):
        file_path = None
        sent_media = None 

        try:
            self._current_message = status_message
            self._current_user_id = update.effective_user.id
            user_id = update.effective_user.id 

            downloader.set_progress_callback(self._download_progress)

            await self.update_message("⬇️ Starting download...")

            metadata, file_path = await downloader.download(url, format_id)

            # SMART CAPTION TRUNCATION
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

            # 🔥 SMALL FILE (< 50MB) - PTB
            if file_size < 50 * 1024 * 1024:
                await self.update_message("⬆️ Uploading to Telegram...\n(Fast mode, please wait)")
                
                with open(file_path, 'rb') as file:
                    if file_path_obj.suffix.lower() in ['.mp3', '.m4a', '.wav']:
                        sent_media = await update.effective_message.reply_audio(
                            audio=file, caption=metadata, parse_mode='HTML',
                            read_timeout=120, write_timeout=120
                        )
                    else:
                        sent_media = await update.effective_message.reply_video(
                            video=file, caption=metadata, parse_mode='HTML', 
                            supports_streaming=True, read_timeout=120, write_timeout=120
                        )

            # 🔥 LARGE FILE (> 50MB) - Pyrogram
            else:
                await self.update_message("⬆️ Preparing large upload...\n(Bypassing limits...)")
                logger.info(f"Pyrogram starting upload for chat {chat_id}, file size: {file_size/1024/1024:.2f} MB")
                
                # Removed the UPLOAD_LIMIT semaphore here to prevent deadlocks!
                # Wrapped in a 10-minute timeout so it CANNOT hang forever silently.
                try:
                    if file_path_obj.suffix.lower() in ['.mp3', '.m4a', '.wav']:
                        sent_media = await asyncio.wait_for(
                            pyro_app.send_audio(
                                chat_id=chat_id, audio=str(file_path), caption=metadata,
                                progress=self.upload_progress, parse_mode=PyroParseMode.HTML
                            ),
                            timeout=600.0 # 10 minute max timeout
                        )
                    else:
                        sent_media = await asyncio.wait_for(
                            pyro_app.send_video(
                                chat_id=chat_id, video=str(file_path), caption=metadata,
                                supports_streaming=True, progress=self.upload_progress, 
                                parse_mode=PyroParseMode.HTML
                            ),
                            timeout=600.0 # 10 minute max timeout
                        )
                    logger.info("Pyrogram upload successful.")
                except asyncio.TimeoutError:
                    logger.error("Pyrogram upload timed out after 10 minutes!")
                    await self.update_message("❌ Upload timed out. The file might be too large.")
                    return

            await self.update_message("✅ Done!")

            if self.activity_logger and sent_media:
                await self.activity_logger.log_media_transfer(
                    message=sent_media, user_id=user_id, url=url
                )

        except Exception as e:
            logger.error(f"Error in process_download: {e}", exc_info=True)
            await update.effective_message.reply_text(f"❌ Download failed: {str(e)[:50]}")

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
        self.activity_logger = activity_logger 

    async def process_download(self, downloader, url, update, status_message, format_id=None):
        worker = DownloadWorker(self.localization, self.settings_manager, self.session, self.activity_logger)
        await worker.process_download(downloader, url, update, status_message, format_id)

    async def cleanup(self):
        if self.session:
            await self.session.close()
