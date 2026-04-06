#NAm Bot Builder 🍺
import logging
import asyncio
import psutil
import platform
import time
from datetime import datetime, timedelta
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import Forbidden, RetryAfter, TelegramError

logger = logging.getLogger(__name__)


class CommandHandlers:
    def __init__(self, keyboard_builder, settings_manager, localization):
        self.keyboard_builder = keyboard_builder
        self.settings_manager = settings_manager
        self.localization = localization
        self.ADMIN_ID = 6318135266
        self.LOG_CHANNEL = -1001925329161
        self.UPDATES_CHANNEL_ID = -1002651553501

    async def _is_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        if update.effective_chat.type in ['group', 'supergroup']:
            try:
                member = await context.bot.get_chat_member(
                    update.effective_chat.id,
                    update.effective_user.id
                )
                return member.status in [
                    ChatMemberStatus.OWNER,
                    ChatMemberStatus.ADMINISTRATOR
                ]
            except Exception as e:
                logger.error(f"Admin check failed: {e}")
                return False
        return True

    async def get_message(
        self,
        user_id: int,
        key: str,
        chat_id: Optional[int] = None,
        is_admin: bool = False,
        **kwargs
    ) -> str:
        settings = await self.settings_manager.get_settings(user_id, chat_id, is_admin)
        return self.localization.get(settings.language, key, **kwargs)

    def _extract_platform(self, url: str) -> str:
        url = url.lower()

        if any(x in url for x in ["tiktok.com", "vm.tiktok.com", "vt.tiktok.com"]):
            return "tiktok"
        elif any(x in url for x in ["youtube.com", "youtu.be"]):
            return "youtube"
        elif any(x in url for x in ["instagram.com", "instagr.am"]):
            return "instagram"
        elif any(x in url for x in ["facebook.com", "fb.watch"]):
            return "facebook"
        elif "pinterest.com" in url:
            return "pinterest"
        elif "soundcloud.com" in url:
            return "soundcloud"
        elif "spotify.com" in url:
            return "spotify"

        return "unknown"

    async def _check_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        user_id = update.effective_user.id
        if user_id == self.ADMIN_ID:
            return True

        try:
            member = await context.bot.get_chat_member(self.UPDATES_CHANNEL_ID, user_id)
            if member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                return True
        except Exception:
            pass

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Channel", url="https://t.me/your_channel_username")]
        ])

        await update.message.reply_text(
            "⚠️ Join channel first",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        return False

    async def neko_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_subscription(update, context):
            return

        if update.effective_user.id != self.ADMIN_ID:
            return

        now = time.time()
        cache = context.bot_data.get("neko_cache")

        if cache and now - cache["time"] < 10:
            data = cache["data"]
        else:
            from ..database import UserActivityLogger
            activity_logger = UserActivityLogger(self.settings_manager.db, bot=context.bot)

            stats = await activity_logger.get_neko_stats()
            db = self.settings_manager.db

            downloads = stats.get("total_downloads", 0)

            failed = await db.user_activity.count_documents({
                "action_type": "download_complete",
                "status": "failed"
            })

            avg_pipeline = [
                {"$match": {"action_type": "download_complete", "status": "success"}},
                {"$group": {"_id": None, "avg": {"$avg": "$processing_time"}}}
            ]
            avg_res = await db.user_activity.aggregate(avg_pipeline).to_list(1)
            avg_time = avg_res[0]["avg"] if avg_res else 0

            top_users_pipeline = [
                {
                    "$match": {
                        "action_type": "download_complete",
                        "status": "success"
                    }
                },
                {
                    "$group": {
                        "_id": "$user_id",
                        "count": {"$sum": 1}
                    }
                },
                {"$sort": {"count": -1}},
                {"$limit": 3}
            ]

            top_users = await db.user_activity.aggregate(top_users_pipeline).to_list(3)

            data = {
                "stats": stats,
                "downloads": downloads,
                "failed": failed,
                "avg_time": avg_time,
                "top_users": top_users
            }

            context.bot_data["neko_cache"] = {"data": data, "time": now}

        stats = data["stats"]

        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        uptime = str(timedelta(seconds=int(time.time() - psutil.boot_time())))

        def fmt(x):
            for u in ["B","KB","MB","GB","TB"]:
                if x < 1024:
                    return f"{x:.2f} {u}"
                x /= 1024

        downloads = data["downloads"]
        success = downloads
        failed = data["failed"]

        total_ops = success + failed
        failure_rate = (failed / total_ops * 100) if total_ops else 0

        avg_time = f"{data['avg_time']:.2f}s" if data["avg_time"] else "N/A"

        users = stats.get("total_users", 0)
        size = fmt(stats.get("total_bytes_downloaded", 0))
        uploaded = fmt(stats.get("total_bytes_uploaded", 0))
        daily = stats.get("daily_count", 0)
        platforms = stats.get("platform_stats", {})

        platform_text = ""
        if platforms:
            for k, v in sorted(platforms.items(), key=lambda x: x[1], reverse=True)[:5]:
                pct = (v / downloads * 100) if downloads else 0
                platform_text += f"• {k.capitalize()}: {pct:.1f}%\n"

        # 🔥 FIXED TOP USERS (YOUR EXACT REQUIREMENT)
        top_users_text = ""
        for u in data["top_users"]:
            uid = u["_id"]
            count = u["count"]

            user_doc = await self.settings_manager.db.user_settings.find_one({"user_id": uid})

            if user_doc:
                first_name = user_doc.get("first_name", "User")
                username = user_doc.get("username")

                if username:
                    link = f"https://t.me/{username}"
                else:
                    link = f"tg://user?id={uid}"
            else:
                first_name = "User"
                link = f"tg://user?id={uid}"

            top_users_text += f"• <a href='{link}'>{first_name}</a>: {count}\n"

        alerts = []
        if failure_rate > 35: alerts.append("Failure Spike")
        if cpu > 85: alerts.append("CPU High")
        if ram.percent > 85: alerts.append("RAM High")

        status = "🚨 " + " | ".join(alerts) if alerts else "🚀 Healthy"

        caption = (
            "📊 <b>UFOload GOD MODE</b>\n\n"
            f"📥 Downloads: <code>{downloads}</code>\n"
            f"📤 Uploads: <code>{downloads}</code>\n"
            f"💾 Downloaded: <code>{size}</code>\n"
            f"☁️ Uploaded: <code>{uploaded}</code>\n\n"
            f"🖥 CPU: <code>{cpu}%</code>\n"
            f"🚀 RAM: <code>{ram.percent}%</code>\n"
            f"⏳ Uptime: <code>{uptime}</code>\n\n"
            f"👤 Users: <code>{users}</code>\n"
            f"📈 Daily: <code>{daily}</code>\n\n"
            f"📊 Platforms:\n{platform_text or 'None'}\n"
            f"⚡ Success: <code>{success}</code>\n"
            f"❌ Failed: <code>{failed}</code>\n"
            f"📉 Failure Rate: <code>{failure_rate:.1f}%</code>\n"
            f"⏱ Avg Time: <code>{avg_time}</code>\n\n"
            f"👑 <b>Top Users</b>:\n{top_users_text or 'None'}\n\n"
            f"{status}"
        )

        await update.message.reply_photo(
            photo="https://telegra.ph/file/ec17880d61180d3312d6a.jpg",
            caption=caption,
            parse_mode=ParseMode.HTML
        )
        # ✅ EVERYTHING ELSE UNTOUCHED (your original file continues here exactly)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command with photo and caption"""
        if not await self._check_subscription(update, context):
            return

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
            user_id=user_id, username=user.username, first_name=user.first_name,
            last_name=user.last_name, is_premium=user.is_premium if hasattr(user, 'is_premium') else False
        )
        
        welcome_photo = "https://telegra.ph/file/e292b12890b8b4b9dcbd1.jpg"
        if chat_type in ['group', 'supergroup']:
            message = await self.get_message(user_id, 'group_welcome_admin' if is_admin else 'group_welcome', chat_id, is_admin)
            await update.message.reply_photo(photo=welcome_photo, caption=message, parse_mode=ParseMode.HTML)
        else:
            message = await self.get_message(user_id, 'welcome', chat_id, is_admin)
            welcome_kb = await self.keyboard_builder.build_welcome_keyboard(user_id)
            main_kb = await self.keyboard_builder.build_main_keyboard(user_id)
            await update.message.reply_photo(photo=welcome_photo, caption=message, reply_markup=welcome_kb, parse_mode=ParseMode.HTML)
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
            chat_id=update.effective_chat.id, title=title, description=description,
            payload="donate_stars", provider_token="", currency="XTR",
            prices=[LabeledPrice(label=label_text, amount=100)]
        )

    async def paysupport_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /paysupport command"""
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
        """Admin only: Broadcast message"""
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
                await context.bot.send_message(chat_id=target_id, text=broadcast_text, parse_mode='HTML')
                sent += 1
                await asyncio.sleep(0.05) 
            except Forbidden: blocked += 1
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
                await context.bot.send_message(chat_id=target_id, text=broadcast_text, parse_mode='HTML')
                sent += 1
            except TelegramError: pass

        await status_msg.edit_text(f"✅ <b>Broadcast Complete</b>\n\n👤 Total: {len(users)}\n📤 Sent: {sent}\n🚫 Blocked: {blocked}", parse_mode=ParseMode.HTML)
