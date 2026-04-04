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

    async def get_message(self, user_id: int, key: str, chat_id: Optional[int] = None, is_admin: bool = False, **kwargs) -> str:
        """Get localized message - NOW ASYNC"""
        settings = await self.settings_manager.get_settings(user_id, chat_id, is_admin)
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
        await self.settings_manager.update_settings(
            user_id=user_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_premium=user.is_premium if hasattr(user, 'is_premium') else False
        )
        
        if chat_type in ['group', 'supergroup']:
            if is_admin:
                message = await self.get_message(user_id, 'group_welcome_admin', chat_id, is_admin)
            else:
                message = await self.get_message(user_id, 'group_welcome', chat_id, is_admin)
            await update.message.reply_text(message, parse_mode=ParseMode.HTML)
        else:
            message = await self.get_message(user_id, 'welcome', chat_id, is_admin)
            welcome_kb = await self.keyboard_builder.build_welcome_keyboard(user_id)
            main_kb = await self.keyboard_builder.build_main_keyboard(user_id)
            
            await update.message.reply_text(
                message,
                reply_markup=welcome_kb,
                parse_mode=ParseMode.HTML
            )
            
            await update.message.reply_text("👇", reply_markup=main_kb)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_admin = await self._is_admin(update, context)
        message = await self.get_message(user_id, 'help', chat_id, is_admin)
        await update.message.reply_text(message)

    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /settings command"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        is_admin = await self._is_admin(update, context)
        
        if chat_type in ['group', 'supergroup'] and not is_admin:
            message = await self.get_message(user_id, 'admin_only', chat_id, is_admin)
            await update.message.reply_text(message)
            return
            
        settings = await self.settings_manager.get_settings(user_id, chat_id, is_admin)
        
        ask_msg = await self.get_message(user_id, 'ask_every_time', chat_id, is_admin)
        best_msg = await self.get_message(user_id, 'best_available', chat_id, is_admin)
        
        quality_display = {
            'ask': ask_msg,
            'best': best_msg
        }.get(settings.default_quality, settings.default_quality)
        
        if chat_type in ['group', 'supergroup']:
            message = await self.get_message(
                user_id, 'group_settings_menu', chat_id, is_admin,
                language=settings.language.upper(), quality=quality_display
            )
        else:
            message = await self.get_message(
                user_id, 'settings_menu', chat_id, is_admin,
                language=settings.language.upper(), quality=quality_display
            )
        
        settings_kb = await self.keyboard_builder.build_settings_keyboard(user_id, chat_id, is_admin)
        await update.message.reply_text(message, reply_markup=settings_kb)

    async def donate_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /donate command"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_admin = await self._is_admin(update, context)

        title = await self.get_message(user_id, 'invoice_title', chat_id, is_admin)
        description = await self.get_message(user_id, 'invoice_description', chat_id, is_admin)
        label_text = await self.get_message(user_id, 'price_label', chat_id, is_admin)
        
        payload = "donate_stars"
        currency = "XTR"  
        prices = [LabeledPrice(label=label_text, amount=100)] 

        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",  
            currency=currency,
            prices=prices
        )

    async def paysupport_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /paysupport command for payment support"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_admin = await self._is_admin(update, context)
        message = await self.get_message(user_id, 'payment_support', chat_id, is_admin)
        await update.message.reply_text(message)

    async def zen_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /zen command"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_admin = await self._is_admin(update, context)
        
        if not context.args:
            message = await self.get_message(user_id, 'missing_url', chat_id, is_admin)
            await update.message.reply_text(message)
            return
        
        url = context.args[0]
        
        from .message_handlers import MessageHandlers
        from ..utils import DownloadManager
        
        message_handler = MessageHandlers(
            self.keyboard_builder,
            self.settings_manager,
            DownloadManager(self.localization, self.settings_manager),
            self.localization
        )
        
        await message_handler._process_url(url, update, context)
