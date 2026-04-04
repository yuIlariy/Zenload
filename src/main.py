from typing import Optional
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# FIX: Switched to AsyncIOMotorClient to match your bot's async architecture
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

class UserSettingsManager:
    def __init__(self):
        self.db = db

    async def setup_indexes(self):
        """Initialize MongoDB collections and indexes asynchronously"""
        try:
            await self.db.user_settings.create_index("user_id", unique=True)
            await self.db.group_settings.create_index("group_id", unique=True)
            await self.db.group_settings.create_index("admin_id")
            logger.info("Database indexes initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize indexes: {e}")

    async def get_settings(self, user_id: int, chat_id: Optional[int] = None, is_admin: bool = False) -> UserSettings:
        """Get settings asynchronously to prevent blocking the event loop"""
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

    async def update_settings(self, user_id: int, **kwargs) -> bool:
        """Update user settings asynchronously"""
        try:
            kwargs['updated_at'] = datetime.utcnow()
            await self.db.user_settings.update_one(
                {"user_id": user_id},
                {"$set": kwargs},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update settings: {e}")
            return False
