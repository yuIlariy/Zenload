import logging
from pathlib import Path
from telegram import Update, Message
from telegram.error import BadRequest
from ..downloaders import DownloadError
import asyncio
import aiohttp
from typing import Dict, Optional, Set
import time
from collections import defaultdict

# Configure logging to prevent duplicates
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

class DownloadWorker:
    """Worker class to handle individual downloads"""
    
    # Static tracker for cookie/auth failures across all instances
    auth_failure_tracker = defaultdict(int)
    ADMIN_ID = 6318135266  # Your Telegram ID

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
        self._update_interval = 0.5  # Minimum time between status updates

    async def get_message(self, user_id: int, key: str, **kwargs) -> str:
        """Get localized message - NOW ASYNC"""
        settings = await self.settings_manager.get_settings(user_id)
        language = settings.language
        return self.localization.get(language, key, **kwargs)

    async def update_status(self, message: Message, user_id: int, status_key: str, progress: int):
        """Update status message with current progress - NOW ASYNC"""
        try:
            current_time = time.time()
            if current_time - self._last_update_time < self._update_interval:
                return

            new_text = await self.get_message(user_id, status_key, progress=progress)
            if new_text == self._last_status and progress == self._last_progress:
                return

            try:
                await asyncio.wait_for(message.edit_text(new_text), timeout=2.0)
                self._last_status = new_text
                self._last_progress = progress
                self._last_update_time = current_time
            except asyncio.TimeoutError:
                logger.debug("Status update timed out, skipping")
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error updating status: {e}")
        except Exception as e:
            logger.error(f"Error updating status: {e}")

    async def _process_status_updates(self):
        """Process status updates asynchronously"""
        try:
            while not self._stop_event.is_set():
                try:
                    status, progress = await asyncio.wait_for(
                        self._status_queue.get(),
                        timeout=0.1
                    )
                    if status == "STOP":
                        break

                    if self._current_message and self._current_user_id:
                        await self.update_status(
                            self._current_message,
                            self._current_user_id,
                            status,
                            progress
                        )
                        self._status_queue.task_done()
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error processing status update: {e}")
        except asyncio.CancelledError:
            pass

    async def progress_callback(self, status: str, progress: int):
        """Async callback for progress updates"""
        try:
            await self._status_queue.put((status, progress))
        except Exception as e:
            logger.error(f"Error in progress callback: {str(e)}")

    async def process_download(self, downloader, url: str, update: Update, status_message: Message, format_id: str = None) -> None:
        """Process content download with error handling, cleanup, and admin logging"""
        user_id = update.effective_user.id
        file_path = None
        start_time = time.time()
        platform = downloader.__class__.__name__.lower().replace('downloader', '')

        if self.activity_logger:
            await self.activity_logger.log_download_attempt(user_id, url, platform)

        try:
            logger.info(f"Starting download for URL: {url}")
            
            self._last_status = None
            self._last_progress = None
            self._current_message = status_message
            self._current_user_id = user_id
            self._stop_event.clear()
            self._last_update_time = 0
            
            self._status_task = asyncio.create_task(self._process_status_updates())
            downloader.set_progress_callback(self.progress_callback)
            
            await self.update_status(status_message, user_id, 'status_getting_info', 0)
            
            metadata, file_path = await downloader.download(url, format_id)
            
            DownloadWorker.auth_failure_tracker[platform] = 0
            
            logger.info(f"Download completed. File path: {file_path}")
            await self.update_status(status_message, user_id, 'status_sending', 0)
            
            sent_media = None
            with open(file_path, 'rb') as file:
                if file_path.suffix.lower() in ['.mp3', '.m4a', '.wav']:
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
            
            # Forward media and link to Admin Log Channel
            if self.activity_logger and sent_media:
                await self.activity_logger.log_media_transfer(
                    message=sent_media,
                    user_id=user_id,
                    url=url
                )

            await self.update_status(status_message, user_id, 'status_sending', 100)
            logger.info("File sent successfully")

        except (DownloadError, Exception) as e:
            error_message = str(e)
            error_lower = error_message.lower()

            if any(key in error_lower for key in ["auth", "cookie", "sign in", "login", "authentication"]):
                DownloadWorker.auth_failure_tracker[platform] += 1
                if DownloadWorker.auth_failure_tracker[platform] >= 5:
                    alert_text = (
                        f"🚨 <b>Cookie Alert!</b>\n\n"
                        f"Platform: <code>{platform}</code>\n"
                        f"Status: 5 consecutive authentication errors detected.\n"
                        f"Action: Update <code>{platform}.txt</code> cookies!"
                    )
                    try:
                        await update.get_bot().send_message(chat_id=self.ADMIN_ID, text=alert_text, parse_mode='HTML')
                    except Exception as alert_err:
                        logger.error(f"Failed to send admin alert: {alert_err}")

            if isinstance(e, DownloadError):
                fail_msg = await self.get_message(user_id, 'download_failed', error=error_message)
                await update.effective_message.reply_text(fail_msg)
            else:
                err_msg = await self.get_message(user_id, 'error_occurred')
                await update.effective_message.reply_text(err_msg)
                logger.error(f"Unexpected error processing {url}: {e}", exc_info=True)

        finally:
            processing_time = time.time() - start_time
            if self.activity_logger:
                success = file_path is not None
                file_type = 'audio' if file_path and file_path.suffix.lower() in ['.mp3', '.m4a', '.wav'] else 'video'
                file_size = Path(file_path).stat().st_size if file_path else None
                error_type = str(e) if 'e' in locals() else None
                
                await self.activity_logger.log_download_complete(
                    user_id=user_id,
                    url=url,
                    success=success,
                    file_type=file_type,
                    file_size=file_size,
                    processing_time=processing_time,
                    error=error_type
                )

            self._stop_event.set()
            if self._status_task:
                await self._status_queue.put(("STOP", 0))
                self._status_task.cancel()
                try:
                    await self._status_task
                except asyncio.CancelledError:
                    pass

            if file_path:
                try:
                    Path(file_path).unlink()
                except Exception as e:
                    logger.error(f"Error deleting file {file_path}: {e}")

            try:
                await status_message.delete()
            except Exception as e:
                logger.error(f"Error deleting status message: {e}")

class DownloadManager:
    """High-performance download manager with optimized concurrency"""
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
        self.rate_limits: Dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(10))

    async def _create_queue(self):
        """Create a new queue bound to the current event loop"""
        try:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)

            if self.download_queue:
                self.download_queue = None

            self.download_queue = asyncio.PriorityQueue()
            logger.info("Successfully created new download queue")
        except Exception as e:
            logger.error(f"Error creating queue: {e}")
            self.download_queue = None

    async def _ensure_initialized(self):
        """Ensure manager is initialized with event loop"""
        try:
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(current_loop)
                current_loop = asyncio.get_running_loop()

            needs_init = (not self._loop or self._loop != current_loop or not self.session or self.session.closed)

            if needs_init:
                await self._cleanup_resources()
                self.connector = aiohttp.TCPConnector(limit=self.max_concurrent_downloads, limit_per_host=20, ssl=False)
                self.session = aiohttp.ClientSession(connector=self.connector, timeout=aiohttp.ClientTimeout(total=300))
                self._loop = current_loop
                self._downloads_lock = asyncio.Lock()
                await self._create_queue()
                self._queue_processor_running = True
                self._queue_processor_task = self._loop.create_task(self._process_queue())
                logger.info("Download manager successfully initialized")
        except Exception as e:
            logger.error(f"Error initializing download manager: {e}")
            await self._cleanup_resources()
            raise

    async def _cleanup_resources(self):
        """Clean up existing resources"""
        if self._queue_processor_task and not self._queue_processor_task.done():
            self._queue_processor_running = False
            self._queue_processor_task.cancel()
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None
        self.connector = None
        self._queue_processor_task = None
        self.download_queue = None

    async def _process_queue(self):
        """Process the download queue"""
        while self._queue_processor_running:
            try:
                if not self.download_queue:
                    await self._create_queue()
                    await asyncio.sleep(1)
                    continue
                try:
                    _, worker, args = await asyncio.wait_for(self.download_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                try:
                    await worker.process_download(*args)
                except Exception as e:
                    logger.error(f"Error processing download: {e}")
                finally:
                    self.download_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Critical error in queue processor: {e}")
                await asyncio.sleep(1)

    async def process_download(self, downloader, url: str, update: Update, status_message: Message, format_id: str = None) -> None:
        """Process download request - NOW ASYNC"""
        await self._ensure_initialized()
        user_id = update.effective_user.id
        async with self._downloads_lock:
            for uid, downloads in list(self.active_downloads.items()):
                self.active_downloads[uid] = {u: task for u, task in downloads.items() if not task.done()}
                if not self.active_downloads[uid]:
                    del self.active_downloads[uid]
            if len(self.active_downloads.get(user_id, {})) >= self.max_downloads_per_user:
                dummy_worker = DownloadWorker(self.localization, self.settings_manager, self.session, self.activity_logger)
                err_text = await dummy_worker.get_message(user_id, 'error_too_many_downloads')
                await status_message.edit_text(err_text)
                return
            worker = DownloadWorker(self.localization, self.settings_manager, self.session, self.activity_logger)
            priority = len(self.active_downloads.get(user_id, {}))
            await self.download_queue.put((priority, worker, (downloader, url, update, status_message, format_id)))

    async def cleanup(self):
        """Cleanup resources on shutdown"""
        try:
            self._queue_processor_running = False
            if self._queue_processor_task:
                self._queue_processor_task.cancel()
            if self.session:
                await self.session.close()
            logger.info("Download manager cleanup completed")
        except Exception as e:
            logger.error(f"Fatal error during cleanup: {e}")
