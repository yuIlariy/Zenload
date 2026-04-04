import logging
import logging.config
from pathlib import Path
import os
import fcntl
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, PreCheckoutQueryHandler, InlineQueryHandler, filters
import signal
import asyncio
import sys

from .config import TOKEN, LOGGING_CONFIG, BASE_DIR
from .database import UserSettingsManager, UserActivityLogger
from .locales import Localization
from .utils import KeyboardBuilder, DownloadManager
from .utils.soundcloud_service import SoundcloudService
from .handlers import CommandHandlers, MessageHandlers, CallbackHandlers, PaymentHandlers, InlineHandlers

# Configure logging
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

class ZenloadBot:
    def __init__(self):
        self.lock_file = None
        self.lock_fd = None
        
        # Try to acquire lock
        try:
            pid_file = Path("/var/run/zenload.pid")
            if not pid_file.parent.exists():
                pid_file = Path(BASE_DIR) / "zenload.pid"
            
            self.lock_file = pid_file
            self.lock_fd = os.open(str(self.lock_file), os.O_RDWR | os.O_CREAT, 0o644)
            
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                os.truncate(self.lock_fd, 0)
                os.write(self.lock_fd, str(os.getpid()).encode())
            except (IOError, OSError) as e:
                logger.error(f"Another instance is already running (Error: {e})")
                os.close(self.lock_fd)
                sys.exit(1)
                
        except Exception as e:
            logger.error(f"Error acquiring lock: {e}")
            if self.lock_fd:
                try:
                    os.close(self.lock_fd)
                except:
                    pass
            sys.exit(1)
            
        # Initialize core components
        self.application = Application.builder().token(TOKEN).build()
        self.settings_manager = UserSettingsManager()
        self.localization = Localization()
        
        # FIX: Pass the bot instance to the activity logger so it can send messages
        self.activity_logger = UserActivityLogger(
            self.settings_manager.db, 
            bot=self.application.bot
        )
        
        self.soundcloud_service = SoundcloudService.get_instance()
        
        # Initialize utility classes
        self.keyboard_builder = KeyboardBuilder(
            self.localization,
            self.settings_manager
        )
        self.download_manager = DownloadManager(
            self.localization,
            self.settings_manager,
            activity_logger=self.activity_logger
        )
        
        # Initialize handlers
        # FIX: Ensure command_handlers has access to the logger for new user logs
        self.command_handlers = CommandHandlers(
            self.keyboard_builder,
            self.settings_manager,
            self.localization
        )
        self.message_handlers = MessageHandlers(
            self.keyboard_builder,
            self.settings_manager,
            self.download_manager,
            self.localization,
            activity_logger=self.activity_logger
        )
        self.callback_handlers = CallbackHandlers(
            self.keyboard_builder,
            self.settings_manager,
            self.download_manager,
            self.localization,
            activity_logger=self.activity_logger
        )
        self.payment_handlers = PaymentHandlers(
            self.localization,
            self.settings_manager
        )
        self.inline_handlers = InlineHandlers(
            self.settings_manager,
            self.localization,
            self.soundcloud_service
        )
        
        self._setup_handlers()
        self._stopping = False

    def _setup_handlers(self):
        """Setup bot command and message handlers"""
        self.application.add_handler(CommandHandler("start", self.command_handlers.start_command))
        self.application.add_handler(CommandHandler("zen", self.command_handlers.zen_command))
        self.application.add_handler(CommandHandler("help", self.command_handlers.help_command))
        self.application.add_handler(CommandHandler("settings", self.command_handlers.settings_command))
        self.application.add_handler(CommandHandler("donate", self.command_handlers.donate_command))
        self.application.add_handler(CommandHandler("paysupport", self.command_handlers.paysupport_command))
        self.application.add_handler(CommandHandler("broadcast", self.command_handlers.broadcast_command))
        self.application.add_handler(PreCheckoutQueryHandler(self.payment_handlers.pre_checkout_callback))
        
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            self.message_handlers.handle_message
        ))
        
        self.application.add_handler(MessageHandler(
            (filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS & filters.Entity("mention")),
            self.message_handlers.handle_message
        ))
        
        self.application.add_handler(CallbackQueryHandler(self.callback_handlers.handle_callback))
        self.application.add_handler(InlineQueryHandler(self.inline_handlers.handle_inline_query))

    async def stop(self):
        """Stop the bot gracefully"""
        if self._stopping:
            return
        
        self._stopping = True
        logger.info("Stopping bot...")
        
        try:
            if self.application.updater:
                try:
                    await asyncio.wait_for(self.application.updater.stop(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Updater stop timed out")
            
            try:
                if hasattr(self.download_manager, 'cleanup'):
                    await asyncio.wait_for(self.download_manager.cleanup(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Download manager cleanup timed out")
            
            if self.application.running:
                try:
                    await asyncio.wait_for(self.application.stop(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Application stop timed out")
                
                try:
                    await asyncio.wait_for(self.application.shutdown(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Application shutdown timed out")
            
            logger.info("Bot stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping bot: {e}", exc_info=True)
        finally:
            try:
                await asyncio.wait_for(self.soundcloud_service.close(), timeout=3)
            except Exception:
                pass

            if self.lock_fd is not None:
                try:
                    fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                    os.close(self.lock_fd)
                    if self.lock_file and self.lock_file.exists():
                        pid = int(self.lock_file.read_text().strip())
                        if pid == os.getpid():
                            self.lock_file.unlink()
                except Exception as e:
                    logger.error(f"Error releasing lock: {e}")
            
            self._stopping = False

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        if self._stopping:
            sys.exit(1)
        
        logger.info(f"Received signal {signum}, initiating graceful shutdown")
        try:
            loop = asyncio.get_event_loop()
        except Exception:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        loop.create_task(self.stop())

    def run(self):
        """Start the bot"""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                loop.run_until_complete(
                    self.application.bot.delete_webhook(drop_pending_updates=True)
                )
                logger.info("Webhook removed before starting polling")
            except Exception as e:
                logger.warning(f"Could not delete webhook: {e}")

            self.application.run_polling(drop_pending_updates=True)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Error running bot: {e}")
            raise
        finally:
            if not self._stopping:
                try:
                    loop = asyncio.get_event_loop()
                    loop.run_until_complete(self.stop())
                except Exception:
                    pass
