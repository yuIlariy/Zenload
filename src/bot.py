import logging
import logging.config
from pathlib import Path
import os
import fcntl
import signal
import asyncio
import sys

from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, PreCheckoutQueryHandler,
    InlineQueryHandler, filters
)

from .config import TOKEN, LOGGING_CONFIG, BASE_DIR
from .database import UserSettingsManager, UserActivityLogger
from .locales import Localization
from .utils import KeyboardBuilder, DownloadManager
from .utils.soundcloud_service import SoundcloudService
from .handlers import (
    CommandHandlers, MessageHandlers,
    CallbackHandlers, PaymentHandlers, InlineHandlers
)

from src.utils.pyro_client import app as pyro_app

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


class ZenloadBot:
    def __init__(self):
        self.lock_file = None
        self.lock_fd = None

        # 🔐 LOCK
        pid_file = Path("/var/run/zenload.pid")
        if not pid_file.parent.exists():
            pid_file = Path(BASE_DIR) / "zenload.pid"

        self.lock_file = pid_file
        self.lock_fd = os.open(str(self.lock_file), os.O_RDWR | os.O_CREAT, 0o644)

        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.truncate(self.lock_fd, 0)
            os.write(self.lock_fd, str(os.getpid()).encode())
        except Exception:
            logger.error("Another instance is running")
            sys.exit(1)

        # 🔥 CORE
        self.application = Application.builder().token(TOKEN).build()
        self.settings_manager = UserSettingsManager()
        self.localization = Localization()

        self.activity_logger = UserActivityLogger(
            self.settings_manager.db,
            bot=self.application.bot
        )

        self.soundcloud_service = SoundcloudService.get_instance()

        self.keyboard_builder = KeyboardBuilder(
            self.localization,
            self.settings_manager
        )

        self.download_manager = DownloadManager(
            self.localization,
            self.settings_manager,
            activity_logger=self.activity_logger
        )

        # 🔥 HANDLERS
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

    def _setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.command_handlers.start_command))
        self.application.add_handler(CommandHandler("help", self.command_handlers.help_command))
        self.application.add_handler(CommandHandler("settings", self.command_handlers.settings_command))

        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.message_handlers.handle_message
        ))

        self.application.add_handler(CallbackQueryHandler(self.callback_handlers.handle_callback))
        self.application.add_handler(InlineQueryHandler(self.inline_handlers.handle_inline_query))

    async def start(self):
        """🔥 Proper unified startup"""
        logger.info("🟢 Starting bot...")

        # remove webhook
        try:
            await self.application.bot.delete_webhook(drop_pending_updates=True)
        except:
            pass

        # 🔥 start pyrogram (ONLY ONCE HERE)
        await pyro_app.start()
        logger.info("🚀 Pyrogram started")

        # 🔥 correct PTB v20+ flow
        await self.application.initialize()
        await self.application.start()

        # 🔥 THIS replaces updater.start_polling + idle
        await self.application.run_polling(drop_pending_updates=True)

    async def stop(self):
        logger.info("Stopping...")

        try:
            await pyro_app.stop()
        except:
            pass

        try:
            await self.application.stop()
            await self.application.shutdown()
        except:
            pass

        try:
            await self.soundcloud_service.close()
        except:
            pass

        if self.lock_fd:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                os.close(self.lock_fd)
                if self.lock_file.exists():
                    self.lock_file.unlink()
            except:
                pass

    def run(self):
        try:
            asyncio.run(self.start())
        except KeyboardInterrupt:
            logger.info("Stopped manually")
