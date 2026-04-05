import logging
import asyncio
import psutil
import platform
import time
from datetime import datetime, timedelta
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

    async def neko_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /neko command for persistent bot and server statistics"""
        user_id = update.effective_user.id
        
        # Security: Only Admin can view detailed server stats
        if user_id != self.ADMIN_ID:
            return

        # 1. Fetch Persistent Metrics from Database
        from ..database import UserActivityLogger
        activity_logger = UserActivityLogger(self.settings_manager.db, bot=context.bot)
        stats_data = await activity_logger.get_neko_stats()
        
        # 2. Server Live Metrics
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Calculate Uptime
        uptime_seconds = time.time() - psutil.boot_time()
        uptime_str = str(timedelta(seconds=int(uptime_seconds)))
        
        # Format File Sizes
        def format_size(bytes_size):
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if bytes_size < 1024:
                    return f"{bytes_size:.2f} {unit}"
                bytes_size /= 1024
            return f"{bytes_size:.2f} PB"

        # Determine Top Platform
        p_stats = stats_data.get('platform_stats', {})
        top_platform = max(p_stats, key=p_stats.get).capitalize() if p_stats else "N/A"

        # Construct Rocket-Style Status Caption
        caption = (
            "📊 <b>UFOload Stats</b>\n\n"
            f"📥 <b>Downloads:</b> <code>{stats_data.get('total_downloads', 0)}</code>\n"
            f"📤 <b>Uploads:</b> <code>{stats_data.get('total_downloads', 0)}</code>\n\n"
            f"💾 <b>Downloaded:</b> <code>{format_size(stats_data.get('total_bytes_downloaded', 0))}</code>\n"
            f"☁️ <b>Uploaded:</b> <code>{format_size(stats_data.get('total_bytes_uploaded', 0))}</code>\n\n"
            f"🖥️ <b>CPU:</b> <code>{cpu}%</code>\n"
            f"🧠 <b>RAM:</b> <code>{ram.percent}%</code>\n"
            f"⏳ <b>Uptime:</b> <code>{uptime_str}</code>\n\n"
            f"👤 <b>Total Users:</b> <code>{stats_data.get('total_users', 0)}</code>\n"
            f"📈 <b>Daily Stats:</b> <code>{stats_data.get('daily_count', 0)} (24h)</code>\n"
            f"🔥 <b>Top Platform:</b> <code>{top_platform}</code>"
        )

        # Thumbnail URL
        photo_url = "https://telegra.ph/file/ec17880d61180d3312d6a.jpg"

        # Send as photo with caption
        await update.message.reply_photo(
            photo=photo_url,
            caption=caption,
            parse_mode=ParseMode.HTML
        )

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command with centralized New User logging"""
        user = update.effective_user
        user_id = user.id
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        is_admin = await self._is_admin(update, context)

        existing_user = await self.settings_manager.db.user_settings.find_one({"user_id": user_id})
        
        if not existing_user:
            from ..database import UserActivityLogger
            activity_logger = UserActivityLogger(self.settings_manager.db, bot=context.bot)
            await activity_logger.log_new_user(user)

        await self.settings_manager.update_settings(
            user_id=user_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_premium=user.is_premium if hasattr(user, 'is_premium') else False
        )
        
        if chat_type in ['group', 'supergroup']:
            message = await self.get_message(user_id, 'group_welcome_admin' if is_admin else 'group_welcome', chat_id, is_admin)
            await update.message.reply_text(message, parse_mode=ParseMode.HTML)
        else:
            message = await self.get_message(user_id, 'welcome', chat_id, is_admin)
            welcome_kb = await self.keyboard_builder.build_welcome_keyboard(user_id)
            main_kb = await self.keyboard_builder.build_main_keyboard(user_id)
            
            await update.message.reply_text(message, reply_markup=welcome_kb, parse_mode=ParseMode.HTML)
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
        
        quality_display = {'ask': ask_msg, 'best': best_msg}.get(settings.default_quality, settings.default_quality)
        
        key = 'group_settings_menu' if chat_type in ['group', 'supergroup'] else 'settings_menu'
        message = await self.get_message(user_id, key, chat_id, is_admin, language=settings.language.upper(), quality=quality_display)
        
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
        
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=title,
            description=description,
            payload="donate_stars",
            provider_token="",  
            currency="XTR",
            prices=[LabeledPrice(label=label_text, amount=100)]
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
            self.keyboard_builder, self.settings_manager,
            DownloadManager(self.localization, self.settings_manager),
            self.localization
        )
        await message_handler._process_url(url, update, context)

    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin only: Send a message to every user in the database"""
        if update.effective_user.id != self.ADMIN_ID:
            return 

        if not context.args:
            await update.message.reply_text("❌ Usage: /broadcast [your message]")
            return

        broadcast_text = " ".join(context.args)
        cursor = self.settings_manager.db.user_settings.find({}, {"user_id": 1})
        users = await cursor.to_list(length=None)

        sent, blocked = 0, 0
        status_msg = await update.message.reply_text(f"🚀 Starting broadcast to {len(users)} users...")

        for user_doc in users:
            target_id = user_doc['user_id']
            try:
                await context.bot.send_message(chat_id=target_id, text=broadcast_text, parse_mode=ParseMode.HTML)
                sent += 1
                await asyncio.sleep(0.05) 
            except Forbidden:
                blocked += 1
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
                await context.bot.send_message(chat_id=target_id, text=broadcast_text, parse_mode=ParseMode.HTML)
                sent += 1
            except TelegramError:
                pass

        await status_msg.edit_text(
            f"✅ <b>Broadcast Complete</b>\n\n👤 Total: {len(users)}\n📤 Sent: {sent}\n🚫 Blocked: {blocked}",
            parse_mode=ParseMode.HTML
        )
