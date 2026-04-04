import logging
from typing import Optional
from telegram import Update, LabeledPrice
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

class CommandHandlers:
    def __init__(self, keyboard_builder, settings_manager, localization):
        self.keyboard_builder = keyboard_builder
        self.settings_manager = settings_manager
        self.localization = localization

    async def _is_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Check if user is an admin in the current chat"""
        if update.effective_chat.type in ['group', 'supergroup']:
            user_id = update.effective_user.id
            chat_id = update.effective_chat.id
            try:
                member = await context.bot.get_chat_member(chat_id, user_id)
                return member.status in ['creator', 'administrator']
            except Exception as e:
                logger.error(f"Failed to check admin status: {e}")
                return False
        return True  # In private chats, user is always "admin"

    def get_message(self, user_id: int, key: str, chat_id: Optional[int] = None, is_admin: bool = False, **kwargs) -> str:
        """Get localized message"""
        settings = self.settings_manager.get_settings(user_id, chat_id, is_admin)
        language = settings.language
        return self.localization.get(language, key, **kwargs)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        is_admin = await self._is_admin(update, context)

        # Save or update user information
        user = update.effective_user
        self.settings_manager.update_settings(
            user_id=user_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_premium=user.is_premium if hasattr(user, 'is_premium') else False
        )
        # Note: phone_number is not available through normal bot API, requires special permissions
        
        if chat_type in ['group', 'supergroup']:
            if is_admin:
                message = self.get_message(user_id, 'group_welcome_admin', chat_id, is_admin)
            else:
                message = self.get_message(user_id, 'group_welcome', chat_id, is_admin)
            await update.message.reply_text(message, parse_mode=ParseMode.HTML)
        else:
            message = self.get_message(user_id, 'welcome', chat_id, is_admin)
            
            # 1. Send the main welcome text with the inline Updates button
            await update.message.reply_text(
                message,
                reply_markup=self.keyboard_builder.build_welcome_keyboard(user_id),
                parse_mode=ParseMode.HTML
            )
            
            # 2. Send a quick pointer to activate the bottom settings menu
            await update.message.reply_text(
                "👇",
                reply_markup=self.keyboard_builder.build_main_keyboard(user_id)
            )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_admin = await self._is_admin(update, context)
        message = self.get_message(user_id, 'help', chat_id, is_admin)
        await update.message.reply_text(message)

    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /settings command"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        is_admin = await self._is_admin(update, context)
        
        # In groups, only admins can change settings
        if chat_type in ['group', 'supergroup'] and not is_admin:
            message = self.get_message(user_id, 'admin_only', chat_id, is_admin)
            await update.message.reply_text(message)
            return
            
        settings = self.settings_manager.get_settings(user_id, chat_id, is_admin)
        
        quality_display = {
            'ask': self.get_message(user_id, 'ask_every_time', chat_id, is_admin),
            'best': self.get_message(user_id, 'best_available', chat_id, is_admin)
        }.get(settings.default_quality, settings.default_quality)
        
        if chat_type in ['group', 'supergroup']:
            message = self.get_message(
                user_id,
                'group_settings_menu',
                chat_id,
                is_admin,
                language=settings.language.upper(),
                quality=quality_display
            )
        else:
            message = self.get_message(
                user_id,
                'settings_menu',
                chat_id,
                is_admin,
                language=settings.language.upper(),
                quality=quality_display
            )
        
        await update.message.reply_text(
            message,
            reply_markup=self.keyboard_builder.build_settings_keyboard(user_id, chat_id, is_admin)
        )

    async def donate_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /donate command"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_admin = await self._is_admin(update, context)

        # Create invoice for Stars payment
        title = self.get_message(user_id, 'invoice_title', chat_id, is_admin)
        description = self.get_message(user_id, 'invoice_description', chat_id, is_admin)
        payload = "donate_stars"
        currency = "XTR"  # Correct Telegram Stars currency code
        prices = [
            LabeledPrice(label=self.get_message(user_id, 'price_label', chat_id, is_admin), amount=100)  # 100 Stars
        ] 

        # Send invoice with single price option
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",  # Empty for Stars payments
            currency=currency,
            prices=prices
        )

    async def paysupport_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /paysupport command for payment support"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_admin = await self._is_admin(update, context)
        await update.message.reply_text(
            self.get_message(user_id, 'payment_support', chat_id, is_admin)
        )

    async def zen_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /zen command"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_admin = await self._is_admin(update, context)
        
        # Extract URL from command arguments
        if not context.args:
            await update.message.reply_text(
                self.get_message(user_id, 'missing_url', chat_id, is_admin)
            )
            return
        
        url = context.args[0]
        
        # Import MessageHandlers here to avoid circular imports
        from .message_handlers import MessageHandlers
        from ..utils import DownloadManager
        
        # Create message handler instance
        message_handler = MessageHandlers(
            self.keyboard_builder,
            self.settings_manager,
            DownloadManager(
                self.localization,
                self.settings_manager
            ),
            self.localization
        )
        
        # Process URL using message handler
        await message_handler._process_url(url, update, context)
