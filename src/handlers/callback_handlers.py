import logging
from typing import Optional, Tuple
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatMemberStatus, ParseMode
from ..downloaders import DownloaderFactory

logger = logging.getLogger(__name__)

class CallbackHandlers:
    def __init__(self, keyboard_builder, settings_manager, download_manager, localization, activity_logger=None):
        self.keyboard_builder = keyboard_builder
        self.settings_manager = settings_manager
        self.download_manager = download_manager
        self.localization = localization
        self.activity_logger = activity_logger
        # Updates Channel ID for verification
        self.UPDATES_CHANNEL_ID = -1002651553501 

    async def _safe_edit(self, query, text, reply_markup=None):
        """✅ Prevent Telegram edit crashes"""
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass

    async def _is_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
        """Check admin status in groups"""
        if chat_id < 0:
            user_id = update.effective_user.id
            try:
                member = await context.bot.get_chat_member(chat_id, user_id)
                return member.status in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR]
            except Exception as e:
                logger.error(f"Failed to check admin status: {e}")
                return False
        return True

    async def get_message(self, user_id: int, key: str, chat_id: Optional[int] = None, is_admin: bool = False, **kwargs) -> str:
        """Get localized text"""
        settings = await self.settings_manager.get_settings(user_id, chat_id, is_admin)
        return self.localization.get(settings.language, key, **kwargs)

    def parse_callback_data(self, data: str) -> Tuple[str, str, Optional[int]]:
        """Parse colon-separated callback data"""
        parts = data.split(':')
        if len(parts) == 3:
            return parts[0], parts[1], int(parts[2])
        return parts[0], parts[1], None

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Main callback entry point with subscription check"""
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id

        # ✅ Handle the 'I have joined' verification button
        if query.data == 'check_sub':
            await self._handle_subscription_check(update, query, context)
            return

        try:
            action, value, chat_id = self.parse_callback_data(query.data)
            is_admin = await self._is_admin(update, context, chat_id) if chat_id else True

            if action == 'quality':
                await self._handle_quality_callback(query, context, user_id, value, chat_id, is_admin)
            elif action == 'settings':
                await self._handle_settings_callback(query, user_id, value, chat_id, is_admin)
            elif action == 'set_lang':
                await self._handle_language_callback(update, query, user_id, value, chat_id, is_admin)
            elif action == 'set_quality':
                await self._handle_quality_setting_callback(query, user_id, value, chat_id, is_admin)

        except Exception as e:
            error_msg = await self.get_message(user_id, 'error_occurred')
            await self._safe_edit(query, error_msg)
            logger.error(f"Error in callback handling: {e}")

    async def _handle_subscription_check(self, update: Update, query, context: ContextTypes.DEFAULT_TYPE):
        """Re-verify membership when user clicks 'I have joined'"""
        user_id = update.effective_user.id
        
        try:
            member = await context.bot.get_chat_member(self.UPDATES_CHANNEL_ID, user_id)
            if member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                # 1. Delete the "Access Denied" warning message
                await query.message.delete()
                
                # 2. Trigger the welcome sequence
                from .command_handlers import CommandHandlers
                cmd_handler = CommandHandlers(self.keyboard_builder, self.settings_manager, self.localization)
                
                # FIX: Check if we need to use query.message instead of update.message
                if update.message:
                    await cmd_handler.start_command(update, context)
                else:
                    # Manually trigger photo sending using the query's message context
                    welcome_photo = "https://telegra.ph/file/e292b12890b8b4b9dcbd1.jpg"
                    message = await cmd_handler.get_message(user_id, 'welcome')
                    welcome_kb = await self.keyboard_builder.build_welcome_keyboard(user_id)
                    main_kb = await self.keyboard_builder.build_main_keyboard(user_id)
                    
                    # Use query.message.reply_photo since update.message is None in callbacks
                    await query.message.reply_photo(
                        photo=welcome_photo,
                        caption=message,
                        reply_markup=welcome_kb,
                        parse_mode=ParseMode.HTML
                    )
                    await query.message.reply_text("👇", reply_markup=main_kb)
            else:
                # Still not in the channel
                await query.answer("⚠️ You still haven't joined the channel!", show_alert=True)
        except Exception as e:
            logger.error(f"Subscription verification failed: {e}")
            await query.answer("❌ Error checking membership. Try again.")

    async def _handle_quality_callback(self, query, context, user_id: int, quality: str, chat_id: Optional[int], is_admin: bool):
        """Handle download quality selection"""
        url = context.user_data.get('pending_url')

        if not url:
            expired_msg = await self.get_message(user_id, 'session_expired', chat_id, is_admin)
            await self._safe_edit(query, expired_msg)
            return

        context.user_data.clear()

        if self.activity_logger:
            await self.activity_logger.log_quality_selection(user_id, url, quality)

        downloader = DownloaderFactory.get_downloader(url)
        if not downloader:
            invalid_msg = await self.get_message(user_id, 'invalid_url', chat_id, is_admin)
            await self._safe_edit(query, invalid_msg)
            return

        if quality == "ask":
            quality = None

        class FakeUpdate:
            def __init__(self, effective_user, effective_message):
                self.effective_user = effective_user
                self.effective_message = effective_message
                self.effective_chat = effective_message.chat

        fake_update = FakeUpdate(
            type('User', (), {'id': user_id})(),
            query.message
        )

        await self.download_manager.process_download(
            downloader,
            url,
            fake_update,
            query.message,
            quality
        )

    async def _handle_settings_callback(self, query, user_id: int, setting: str, chat_id: Optional[int], is_admin: bool):
        """Navigate settings"""
        if chat_id and chat_id < 0 and not is_admin:
            admin_msg = await self.get_message(user_id, 'admin_only', chat_id, is_admin)
            await self._safe_edit(query, admin_msg)
            return

        if setting == 'language':
            msg = await self.get_message(user_id, 'select_language', chat_id, is_admin)
            kb = await self.keyboard_builder.build_language_keyboard(user_id, chat_id, is_admin)
            await self._safe_edit(query, msg, kb)

        elif setting == 'quality':
            msg = await self.get_message(user_id, 'select_default_quality', chat_id, is_admin)
            kb = await self.keyboard_builder.build_quality_keyboard(user_id, chat_id, is_admin)
            await self._safe_edit(query, msg, kb)

        elif setting == 'back':
            await self._show_settings_menu(query, user_id, chat_id, is_admin)

    async def _show_settings_menu(self, query, user_id: int, chat_id: Optional[int], is_admin: bool):
        """Show settings"""
        settings = await self.settings_manager.get_settings(user_id, chat_id, is_admin)
        ask_msg = await self.get_message(user_id, 'ask_every_time', chat_id, is_admin)
        best_msg = await self.get_message(user_id, 'best_available', chat_id, is_admin)

        quality_display = {
            'ask': ask_msg,
            'best': best_msg,
            'audio': "Audio (MP3)"
        }.get(settings.default_quality, settings.default_quality)

        message_key = 'group_settings_menu' if chat_id and chat_id < 0 else 'settings_menu'
        msg = await self.get_message(
            user_id, message_key, chat_id, is_admin,
            language=settings.language.upper(),
            quality=quality_display
        )

        kb = await self.keyboard_builder.build_settings_keyboard(user_id, chat_id, is_admin)
        await self._safe_edit(query, msg, kb)

    async def _handle_language_callback(self, update, query, user_id: int, language: str, chat_id: Optional[int], is_admin: bool):
        """Language logic"""
        if chat_id and chat_id < 0 and not is_admin:
            admin_msg = await self.get_message(user_id, 'admin_only', chat_id, is_admin)
            await self._safe_edit(query, admin_msg)
            return

        current_settings = await self.settings_manager.get_settings(user_id, chat_id, is_admin)
        if current_settings.language == language:
            unchanged_msg = await self.get_message(user_id, 'settings_unchanged', chat_id, is_admin)
            await self._safe_edit(query, unchanged_msg)
            return

        await self.settings_manager.update_settings(user_id, chat_id=chat_id, is_admin=is_admin, language=language)

        if not chat_id or chat_id > 0:
            welcome_msg = await self.get_message(user_id, 'welcome', chat_id, is_admin)
            main_kb = await self.keyboard_builder.build_main_keyboard(user_id)
            await update.effective_message.reply_text(welcome_msg, reply_markup=main_kb)

        await self._show_settings_menu(query, user_id, chat_id, is_admin)

    async def _handle_quality_setting_callback(self, query, user_id: int, quality: str, chat_id: Optional[int], is_admin: bool):
        """Quality setting logic"""
        if chat_id and chat_id < 0 and not is_admin:
            admin_msg = await self.get_message(user_id, 'admin_only', chat_id, is_admin)
            await self._safe_edit(query, admin_msg)
            return

        current_settings = await self.settings_manager.get_settings(user_id, chat_id, is_admin)
        if current_settings.default_quality == quality:
            unchanged_msg = await self.get_message(user_id, 'settings_unchanged', chat_id, is_admin)
            await self._safe_edit(query, unchanged_msg)
            return

        await self.settings_manager.update_settings(user_id, chat_id=chat_id, is_admin=is_admin, default_quality=quality)
        await self._show_settings_menu(query, user_id, chat_id, is_admin)
