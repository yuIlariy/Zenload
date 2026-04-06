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
        # Official log channel ID
        self.LOG_CHANNEL = -1001925329161 

    async def log_new_user(self, user):
        """Send formatted 'New User' log with a clickable mention"""
        if not self.bot or not self.LOG_CHANNEL:
            return

        text = (
            "🚀 <u><b>ɴᴇᴡ ᴜꜱᴇʀ ꜱᴛᴀʀᴛᴇᴅ ᴛʜᴇ ʙᴏᴛ</b></u>\n\n"
            f"📜 User: <a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"👤 UN: @{user.username if user.username else 'None'}\n\n"
            f"🗓 DATE: {datetime.now().strftime('%d %B, %Y')}\n"
            f"⏰ TIME: {datetime.now().strftime('%I:%M:%S %p')}"
        )

        try:
            await self.bot.send_message(
                chat_id=self.LOG_CHANNEL,
                text=text,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Failed to send new user log to channel: {e}")
            

    async def log_media_transfer(self, message, user_id: int, url: str):
        """Forward media to log channel and provide the original link"""
        if not self.bot or not self.LOG_CHANNEL or not message:
            return

        try:
            await message.forward(chat_id=self.LOG_CHANNEL)
            
            log_metadata = (
                f"🔗 <b>Source Link:</b> {url}\n"
                f"👤 <b>User ID:</b> <code>{user_id}</code>"
            )
            await self.bot.send_message(
                chat_id=self.LOG_CHANNEL,
                text=log_metadata,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Failed to forward media to log channel: {e}")

    async def setup_indexes(self):
        """Initialize MongoDB collection and indexes asynchronously"""
        await self.db.user_activity.create_index([("user_id", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)])
        await self.db.user_activity.create_index([("platform", pymongo.ASCENDING)])
        await self.db.user_activity.create_index([("status", pymongo.ASCENDING)])
        await self.db.user_activity.create_index([("timestamp", pymongo.DESCENDING)])
        await self.db.global_stats.create_index("_id")

    async def log_download_attempt(self, user_id: int, url: str, platform: str):
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
        """Log download and update persistent global metrics"""
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

        # Update Persistent Global Stats if successful
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
        """Retrieve persistent and live statistics for the /neko command"""
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
        """✅ FIXED: Categorize URLs for stats, including Spotify and Instagram short links"""
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
        return "unknown"


class UserSettingsManager:
    def __init__(self):
        self.db = db

    async def setup_indexes(self):
        """Initialize MongoDB collections and indexes asynchronously"""
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
