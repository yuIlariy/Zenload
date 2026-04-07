from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict
from motor.motor_asyncio import AsyncIOMotorClient
import pymongo
import os
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Initialize MongoDB connection asynchronously
client = AsyncIOMotorClient(os.getenv('MONGODB_URI'))
db = client.zenload


@dataclass
class UserSettings:
    user_id: int
    language: str = 'en'
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    is_premium: bool = False
    default_quality: str = 'best'
    created_at: datetime = None
    updated_at: datetime = None


@dataclass
class GroupSettings:
    group_id: int
    admin_id: int
    language: str = 'en'
    default_quality: str = 'best'
    created_at: datetime = None
    updated_at: datetime = None


@dataclass
class UserActivity:
    user_id: int
    action_type: str
    timestamp: datetime
    url: str
    platform: str
    status: str = None
    error_type: str = None
    quality: str = None
    file_type: str = None
    file_size: int = None
    processing_time: float = None


class UserActivityLogger:
    def __init__(self, db, bot=None):
        self.db = db
        self.bot = bot
        self.LOG_CHANNEL = -1001925329161 

    async def log_new_user(self, user):
        if self.bot is None or self.LOG_CHANNEL is None:
            return

        try:
            bot_name = "Bot"
            bot_username = None

            try:
                if not hasattr(self, "bot_info"):
                    self.bot_info = await self.bot.get_me()
                bot_name = self.bot_info.first_name or "Bot"
                bot_username = self.bot_info.username
            except Exception:
                pass

            username = f"@{user.username}" if user.username else "N/A"

            if bot_username:
                bot_link = f"<a href='https://t.me/{bot_username}'>{bot_name}</a>"
            else:
                bot_link = bot_name

            text = (
                "🚀 <b><u>New User Started the Bot</u></b>\n\n"
                f"<b>👤 User:</b> <a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
                f"<b>🆔 ID:</b> <code>{user.id}</code>\n"
                f"<b>🔗 Username:</b> {username}\n\n"
                f"<b>📅 Date:</b> {datetime.now().strftime('%d %B %Y')}\n"
                f"<b>⏰ Time:</b> {datetime.now().strftime('%I:%M:%S %p')}\n\n"
                f"🚀 <b>Started:</b> {bot_link}"
            )

            await self.bot.send_message(
                chat_id=self.LOG_CHANNEL,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )

        except Exception as e:
            logger.error(f"Failed to send new user log to channel: {e}")

    async def log_media_transfer(
        self,
        message,
        user_id: int,
        url: str,
        success: bool = True,
        file_size: int = None,
        processing_time: float = None
    ):
        """Forward media to log channel with rich metadata"""
        if self.bot is None or self.LOG_CHANNEL is None or message is None:
            return

        try:
            await message.forward(chat_id=self.LOG_CHANNEL)

            # 👤 User mention
            try:
                name = message.from_user.first_name or "User"
                user_mention = f"<a href='tg://user?id={user_id}'>{name}</a>"
            except Exception:
                user_mention = f"<code>{user_id}</code>"

            # 🌐 Platform
            platform = self._extract_platform(url).capitalize()

            # 📦 Size formatter
            def format_size(size):
                if not size:
                    return "N/A"
                for unit in ["B", "KB", "MB", "GB"]:
                    if size < 1024:
                        return f"{size:.1f} {unit}"
                    size /= 1024
                return f"{size:.1f} TB"

            size_text = format_size(file_size)

            # ⚡ Status
            status = "✅ Success" if success else "❌ Failed"

            # ⏱ Time
            time_text = f"{processing_time:.2f}s" if processing_time else "N/A"

            log_metadata = (
                f"🍺 <b>Download Log</b>\n\n"
                f"🔗 <b>Source:</b> {url}\n\n"
                f"👤 <b>User:</b> {user_mention}\n"
                f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                f"🌐 <b>Platform:</b> {platform}\n\n"
                f"📦 <b>Size:</b> {size_text}\n"
                f"⚡ <b>Status:</b> {status}\n"
                f"⏱ <b>Time:</b> {time_text}"
            )

            await self.bot.send_message(
                chat_id=self.LOG_CHANNEL,
                text=log_metadata,
                parse_mode="HTML",
                disable_web_page_preview=True
            )

        except Exception as e:
            logger.error(f"Failed to forward media to log channel: {e}")

    async def setup_indexes(self):
        await self.db.user_activity.create_index([("user_id", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)])
        await self.db.user_activity.create_index([("platform", pymongo.ASCENDING)])
        await self.db.user_activity.create_index([("status", pymongo.ASCENDING)])
        await self.db.user_activity.create_index([("timestamp", pymongo.DESCENDING)])
        await self.db.global_stats.create_index("_id")

    async def log_download_attempt(self, user_id: int, url: str, platform: str):
        # ✅ FIXED: Comparing explicitly to None
        if getattr(self, 'db', None) is None:
            return None
            
        activity = UserActivity(
            user_id=user_id,
            action_type="download_start",
            timestamp=datetime.utcnow(),
            url=url,
            platform=platform
        )
        await self.db.user_activity.insert_one(activity.__dict__)
        return activity

    async def log_download_complete(self, user_id: int, url: str, success: bool,
                            file_type: str = None, file_size: int = None,
                            processing_time: float = None, error: str = None):
        # ✅ FIXED: Comparing explicitly to None
        if getattr(self, 'db', None) is None:
            return None
            
        platform = self._extract_platform(url)
        activity = UserActivity(
            user_id=user_id,
            action_type="download_complete",
            timestamp=datetime.utcnow(),
            url=url,
            platform=platform,
            status="success" if success else "failed",
            error_type=error,
            file_type=file_type,
            file_size=file_size,
            processing_time=processing_time
        )
        await self.db.user_activity.insert_one(activity.__dict__)

        if success:
            actual_size = file_size if file_size else 0
            await self.db.global_stats.update_one(
                {"_id": "totals"},
                {
                    "$inc": {
                        "total_downloads": 1,
                        "total_bytes_downloaded": actual_size,
                        "total_bytes_uploaded": actual_size,
                        f"platform_stats.{platform}": 1
                    }
                },
                upsert=True
            )
        return activity

    async def get_neko_stats(self) -> dict:
        db_stats = await self.db.global_stats.find_one({"_id": "totals"}) or {}
        total_users = await self.db.user_settings.count_documents({})
        
        last_24h = datetime.utcnow() - timedelta(hours=24)
        daily_count = await self.db.user_activity.count_documents({
            "action_type": "download_complete",
            "status": "success",
            "timestamp": {"$gte": last_24h}
        })

        return {
            "total_downloads": db_stats.get("total_downloads", 0),
            "total_bytes_downloaded": db_stats.get("total_bytes_downloaded", 0),
            "total_bytes_uploaded": db_stats.get("total_bytes_uploaded", 0),
            "platform_stats": db_stats.get("platform_stats", {}),
            "total_users": total_users,
            "daily_count": daily_count
        }

    async def log_quality_selection(self, user_id: int, url: str, quality: str):
        # ✅ FIXED: Comparing explicitly to None
        if getattr(self, 'db', None) is None:
            return None
            
        activity = UserActivity(
            user_id=user_id,
            action_type="quality_select",
            timestamp=datetime.utcnow(),
            url=url,
            platform=self._extract_platform(url),
            quality=quality
        )
        await self.db.user_activity.insert_one(activity.__dict__)
        return activity

    def _extract_platform(self, url: str) -> str:
        url_lower = url.lower()
        if "youtube.com" in url_lower or "youtu.be" in url_lower:
            return "youtube"
        elif "instagram.com" in url_lower or "instagr.am" in url_lower:
            return "instagram"
        elif "tiktok.com" in url_lower:
            return "tiktok"
        elif "spotify.com" in url_lower or "open.spotify.com" in url_lower:
            return "spotify"
        elif "facebook.com" in url_lower or "fb.watch" in url_lower:
            return "facebook"
        elif "pinterest.com" in url_lower:
            return "pinterest"
        elif "yandex" in url_lower:
            return "yandex"
        elif "soundcloud.com" in url_lower:
            return "soundcloud"
        elif "x.com" in url_lower or "twitter.com" in url_lower:
            return "twitter"
        elif "reddit.com" in url_lower:
            return "reddit"
        return "universal"


class UserSettingsManager:
    def __init__(self):
        self.db = db

    async def setup_indexes(self):
        await self.db.user_settings.create_index("user_id", unique=True)
        await self.db.group_settings.create_index("group_id", unique=True)
        await self.db.group_settings.create_index("admin_id")

    async def get_settings(self, user_id: int, chat_id: Optional[int] = None, is_admin: bool = False) -> UserSettings:
        try:
            if chat_id and chat_id < 0:
                group_doc = await self.db.group_settings.find_one({"group_id": chat_id})
                if group_doc:
                    return UserSettings(
                        user_id=user_id,
                        language=group_doc.get('language', 'en'),
                        default_quality=group_doc.get('default_quality', 'ask')
                    )
            
            user_doc = await self.db.user_settings.find_one({"user_id": user_id})

            if not user_doc:
                settings = UserSettings(user_id=user_id)
                await self.db.user_settings.insert_one({
                    "user_id": user_id,
                    "language": settings.language,
                    "default_quality": settings.default_quality,
                    "username": None,
                    "first_name": None,
                    "last_name": None,
                    "phone_number": None,
                    "is_premium": False,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                })
                return settings
            
            return UserSettings(
                user_id=user_id,
                language=user_doc.get('language', 'en'),
                default_quality=user_doc.get('default_quality', 'ask'),
                username=user_doc.get('username'),
                first_name=user_doc.get('first_name'),
                last_name=user_doc.get('last_name'),
                phone_number=user_doc.get('phone_number'),
                is_premium=user_doc.get('is_premium', False),
                created_at=user_doc.get('created_at'),
                updated_at=user_doc.get('updated_at')
            )

        except Exception as e:
            logger.error(f"Failed to get settings for user {user_id}: {e}")
            return UserSettings(user_id=user_id)

    async def update_settings(self, user_id: int, chat_id: Optional[int] = None, is_admin: bool = False, **kwargs) -> UserSettings:
        try:
            if chat_id and chat_id < 0 and is_admin:
                valid_fields = {'language', 'default_quality'}
                update_fields = {k: v for k, v in kwargs.items() if k in valid_fields}
                
                if update_fields:
                    update_fields['updated_at'] = datetime.utcnow()
                    await self.db.group_settings.update_one(
                        {"group_id": chat_id},
                        {
                            "$set": update_fields,
                            "$setOnInsert": {
                                "group_id": chat_id,
                                "admin_id": user_id,
                                "created_at": datetime.utcnow()
                            }
                        },
                        upsert=True
                    )
                    return await self.get_settings(user_id, chat_id, is_admin)
            
            valid_fields = {'language', 'default_quality', 'username', 'first_name', 'last_name', 'phone_number', 'is_premium'}
            update_fields = {k: v for k, v in kwargs.items() if k in valid_fields}
            
            if update_fields:
                update_fields['updated_at'] = datetime.utcnow()
                await self.db.user_settings.update_one(
                    {"user_id": user_id},
                    {
                        "$set": update_fields,
                        "$setOnInsert": {
                            "user_id": user_id,
                            "created_at": datetime.utcnow()
                        }
                    },
                    upsert=True
                )
            return await self.get_settings(user_id)

        except Exception as e:
            logger.error(f"Failed to update settings for user {user_id}: {e}")
            return await self.get_settings(user_id)

    async def get_group_admin(self, group_id: int) -> Optional[int]:
        try:
            group_doc = await self.db.group_settings.find_one({"group_id": group_id})
            return group_doc['admin_id'] if group_doc else None
        except Exception as e:
            logger.error(f"Failed to get admin for group {group_id}: {e}")
            return None
