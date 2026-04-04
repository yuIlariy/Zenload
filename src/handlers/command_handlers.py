import logging
import asyncio
from datetime import datetime
from typing import Optional
from telegram import Update, LabeledPrice
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import Forbidden, RetryAfter, TelegramError

logger = logging.getLogger(__name__)

class CommandHandlers:
    def __init__(self, keyboard_builder, settings_manager, localization):
        self.keyboard_builder = keyboard_builder
        self.settings_manager = settings_manager
        self.localization = localization
        self.ADMIN_ID = 6318135266  # Your Telegram ID
        self.LOG_CHANNEL = -1001925329161  # Your Log Channel ID

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
        """Handle /start command with New User logging"""
        user = update.effective_user
        user_id = user.id
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        is_admin = await self._is_admin(update, context)

        # Check if this is a brand new user to trigger the Rocket Log
        existing_user = await self.settings_manager.db.user_settings.find_one({"user_id": user_id})
        if not existing_user:
            # Rocket-style New User Log based on your provided format
            log_text = (
                "🚀 <u><b>NEW USER STARTED THE BOT</b></u>\n\n"
                f"📜 User: {user.first_name}\n"
                f"🆔 ID: <code>{user.id}</code>\n"
                f"👤 UN: @{user.username if user.username else 'None'}\n\n"
                f"🗓 DATE: {datetime.now().strftime('%d %B, %Y')}\n"
                f"⏰ TIME: {datetime.now().strftime('%I:%M:%S %p')}"
            )
            try:
                await context.bot.send_message(chat_id=self.LOG_CHANNEL, text=log_text, parse_mode='HTML')
            except Exception as e:
                logger.error(f"Failed to send new user log: {e}")

        # Save or update user information
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

    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin only: Send a message to every user in the database"""
        user_id = update.effective_user.id
        
        if user_id != self.ADMIN_ID:
            return 

        if not context.args:
            await update.message.reply_text("❌ Usage: /broadcast [your message]")
            return

        broadcast_text = " ".join(context.args)
        cursor = self.settings_manager.db.user_settings.find({}, {"user_id": 1})
        users = await cursor.to_list(length=None)

        sent_count = 0
        blocked_count = 0
        
        status_msg = await update.message.reply_text(f"🚀 Starting broadcast to {len(users)} users...")

        for user_doc in users:
            target_id = user_doc['user_id']
            try:
                await context.bot.send_message(chat_id=target_id, text=broadcast_text, parse_mode='HTML')
                sent_count += 1
                await asyncio.sleep(0.05) 
            except Forbidden:
                blocked_count += 1
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
                await context.bot.send_message(chat_id=target_id, text=broadcast_text, parse_mode='HTML')
                sent_count += 1
            except TelegramError as e:
                logger.error(f"Failed to send to {target_id}: {e}")
                pass

        await status_msg.edit_text(
            f"✅ <b>Broadcast Complete</b>\n\n"
            f"👤 Total users found: {len(users)}\n"
            f"📤 Successfully sent: {sent_count}\n"
            f"🚫 Blocked/Bot stopped: {blocked_count}",
            parse_mode=ParseMode.HTML
        )
