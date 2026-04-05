import logging
from telegram import Update, Chat
from telegram.ext import ContextTypes
import re
from ..downloaders import DownloaderFactory
import asyncio

logger = logging.getLogger(__name__)

class MessageHandlers:
    def __init__(self, keyboard_builder, settings_manager, download_manager, localization, activity_logger=None):
        self.keyboard_builder = keyboard_builder
        self.settings_manager = settings_manager
        self.download_manager = download_manager
        self.localization = localization
        self.activity_logger = activity_logger
        self._download_tasks = {}
        # Reference to command handlers for the subscription check
        from .command_handlers import CommandHandlers
        self.command_handlers = CommandHandlers(self.keyboard_builder, self.settings_manager, self.localization)

    async def get_message(self, user_id: int, key: str, **kwargs) -> str:
        """Get localized message - NOW ASYNC"""
        settings = await self.settings_manager.get_settings(user_id)
        language = settings.language
        return self.localization.get(language, key, **kwargs)
        
    def _extract_url(self, text: str) -> str:
        """Extract URL from text"""
        if not text:
            return None
        urls = re.findall(r'https?://[^\s]+', text)
        return urls[0] if urls else None

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages with subscription verification"""
        message = update.message
        user_id = update.effective_user.id
        
        # 1. Force Subscribe Check
        # This blocks users from sending links if they haven't joined the channel
        if not await self.command_handlers._check_subscription(update, context):
            return

        # Update user information
        user = update.effective_user
        await self.settings_manager.update_settings(
            user_id=user_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_premium=user.is_premium if hasattr(user, 'is_premium') else False
        )

        message_text = message.text or ''

        # Handle group chat messages
        if update.effective_chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
            bot_username = context.bot.username
            if not bot_username or f"@{bot_username}" not in message_text:
                return
                
            url = self._extract_url(message_text)
            if not url and message.reply_to_message:
                replied_text = message.reply_to_message.text
                url = self._extract_url(replied_text)
            
            if url:
                asyncio.create_task(self._process_url(url, update, context))
            return

        # Handle private chat shortcuts
        message_text_strip = message_text.strip()
        if await self._handle_keyboard_shortcuts(message_text_strip, user_id, update, context):
            return

        # Process URL in private chat
        url = self._extract_url(message_text_strip)
        if url:
            asyncio.create_task(self._process_url(url, update, context))
        else:
            unsupported_msg = await self.get_message(user_id, 'unsupported_url')
            await message.reply_text(unsupported_msg)
            
    async def _handle_keyboard_shortcuts(self, message_text: str, user_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Handle keyboard shortcuts"""
        btn_settings = await self.get_message(user_id, 'btn_settings')
        btn_help = await self.get_message(user_id, 'btn_help')
        btn_donate = await self.get_message(user_id, 'btn_donate')

        if message_text == btn_settings:
            await self.command_handlers.settings_command(update, context)
            return True
        elif message_text == btn_help:
            await self.command_handlers.help_command(update, context)
            return True
        elif message_text == btn_donate:
            await self.command_handlers.donate_command(update, context)
            return True

        return False

    async def _process_url(self, url: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process URL logic"""
        user_id = update.effective_user.id
        
        downloader = DownloaderFactory.get_downloader(url)
        if not downloader:
            unsupported_msg = await self.get_message(user_id, 'unsupported_url')
            await update.message.reply_text(unsupported_msg)
            return

        processing_msg = await self.get_message(user_id, 'processing')
        status_message = await update.message.reply_text(processing_msg)

        if not status_message:
            return 

        try:
            formats = await downloader.get_formats(url)
            
            if formats:
                if not context.user_data:
                    context.user_data.clear()
                context.user_data['pending_url'] = url

                settings = await self.settings_manager.get_settings(user_id)
                
                if settings.default_quality != 'ask':
                    download_task = asyncio.create_task(
                        self.download_manager.process_download(
                            downloader, url, update, status_message, settings.default_quality
                        )
                    )
                    task_key = f"{user_id}:{url}"
                    self._download_tasks[task_key] = download_task
                    download_task.add_done_callback(lambda t: self._download_tasks.pop(task_key, None))
                    return
                
                select_quality_msg = await self.get_message(user_id, 'select_quality')
                format_kb = await self.keyboard_builder.build_format_selection_keyboard(user_id, formats)
                await status_message.edit_text(select_quality_msg, reply_markup=format_kb)
            else:
                download_task = asyncio.create_task(
                    self.download_manager.process_download(downloader, url, update, status_message)
                )
                task_key = f"{user_id}:{url}"
                self._download_tasks[task_key] = download_task
                download_task.add_done_callback(lambda t: self._download_tasks.pop(task_key, None))

        except Exception as e:
            error_msg = await self.get_message(user_id, 'error_occurred')
            await update.message.reply_text(error_msg)
            logger.error(f"Unexpected error processing {url}: {e}")
            await status_message.delete()
