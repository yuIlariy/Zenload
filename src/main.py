from typing import Optional
from datetime import datetime
from pymongo import MongoClient, ASCENDING
from pymongo.database import Database
import os
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Initialize MongoDB connection
client = MongoClient(os.getenv('MONGODB_URI'))
db: Database = client.zenload

@dataclass
class UserSettings:
    user_id: int
    language: str = 'en'  # Updated default to English
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    is_premium: bool = False
    default_quality: str = 'best'
    created_at: datetime = None
    updated_at: datetime = None

# ... (GroupSettings and UserActivity classes remain the same)

class UserSettingsManager:
    def __init__(self):
        self.db = db
        self._init_collections()

    def _init_collections(self):
        self.db.user_settings.create_index("user_id", unique=True)
        self.db.group_settings.create_index("group_id", unique=True)
        self.db.group_settings.create_index("admin_id")

    def get_settings(self, user_id: int, chat_id: Optional[int] = None, is_admin: bool = False) -> UserSettings:
        try:
            if chat_id and chat_id < 0:
                group_doc = self.db.group_settings.find_one({"group_id": chat_id})
                if group_doc:
                    return UserSettings(
                        user_id=user_id,
                        language=group_doc.get('language', 'en'), # Default to en
                        default_quality=group_doc.get('default_quality', 'ask')
                    )
            
            user_doc = self.db.user_settings.find_one({"user_id": user_id})
            if not user_doc:
                settings = UserSettings(user_id=user_id)
                self.db.user_settings.insert_one({
                    "user_id": user_id,
                    "language": settings.language,
                    "default_quality": settings.default_quality,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                })
                return settings
            
            return UserSettings(
                user_id=user_id,
                language=user_doc.get('language', 'en'), # Default to en
                default_quality=user_doc.get('default_quality', 'ask'),
                # ... (rest of fields)
            )
        except Exception as e:
            logger.error(f"Failed to get settings: {e}")
            return UserSettings(user_id=user_id)
