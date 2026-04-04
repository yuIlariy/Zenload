from typing import Optional
from datetime import datetime, timedelta
from collections import defaultdict
from pymongo import MongoClient, ASCENDING, DESCENDING
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
    action_type: str  # download_start, download_complete, quality_select
    timestamp: datetime
    url: str
    platform: str
    status: str = None  # success, failed
    error_type: str = None
    quality: str = None
    file_type: str = None
    file_size: int = None
    processing_time: float = None

class UserActivityLogger:
    def __init__(self, db: Database):
        self.db = db
        self._init_collection()

    def _init_collection(self):
        """Initialize MongoDB collection and indexes"""
        # Create indexes for efficient querying
        self.db.user_activity.create_index([("user_id", ASCENDING), ("timestamp", DESCENDING)])
        self.db.user_activity.create_index([("platform", ASCENDING)])
        self.db.user_activity.create_index([("status", ASCENDING)])
        self.db.user_activity.create_index([("timestamp", DESCENDING)])

    def log_download_attempt(self, user_id: int, url: str, platform: str):
        """Log when user attempts to download content"""
        activity = UserActivity(
            user_id=user_id,
            action_type="download_start",
            timestamp=datetime.utcnow(),
            url=url,
            platform=platform
        )
        self.db.user_activity.insert_one(activity.__dict__)
        return activity

    def log_download_complete(self, user_id: int, url: str, success: bool,
                            file_type: str = None, file_size: int = None,
                            processing_time: float = None, error: str = None):
        """Log when download completes (successfully or with error)"""
        activity = UserActivity(
            user_id=user_id,
            action_type="download_complete",
            timestamp=datetime.utcnow(),
            url=url,
            platform=self._extract_platform(url),
            status="success" if success else "failed",
            error_type=error,
            file_type=file_type,
            file_size=file_size,
            processing_time=processing_time
        )
        self.db.user_activity.insert_one(activity.__dict__)
        return activity

    def log_quality_selection(self, user_id: int, url: str, quality: str):
        """Log when user selects quality"""
        activity = UserActivity(
            user_id=user_id,
            action_type="quality_select",
            timestamp=datetime.utcnow(),
            url=url,
            platform=self._extract_platform(url),
            quality=quality
        )
        self.db.user_activity.insert_one(activity.__dict__)
        return activity

    def _extract_platform(self, url: str) -> str:
        """Extract platform name from URL"""
        if "youtube.com" in url or "youtu.be" in url:
            return "youtube"
        elif "instagram.com" in url:
            return "instagram"
        elif "tiktok.com" in url:
            return "tiktok"
        elif "pinterest.com" in url:
            return "pinterest"
        elif "disk.yandex.ru" in url:
            return "yandex"
        return "unknown"

    def get_user_stats(self, user_id: int, days: int = 30) -> dict:
        """Get statistics for a specific user"""
        start_date = datetime.utcnow() - timedelta(days=days)
        
        pipeline = [
            {"$match": {
                "user_id": user_id,
                "timestamp": {"$gte": start_date}
            }},
            {"$group": {
                "_id": {
                    "platform": "$platform",
                    "status": "$status"
                },
                "count": {"$sum": 1},
                "avg_processing_time": {"$avg": "$processing_time"}
            }}
        ]
        
        results = self.db.user_activity.aggregate(pipeline)
        
        stats = {
            "total_downloads": 0,
            "successful_downloads": 0,
            "failed_downloads": 0,
            "platforms": defaultdict(lambda: {"success": 0, "failed": 0}),
            "avg_processing_time": 0
        }
        
        for result in results:
            platform = result["_id"]["platform"]
            status = result["_id"]["status"]
            count = result["count"]
            
            if status == "success":
                stats["successful_downloads"] += count
                stats["platforms"][platform]["success"] = count
            elif status == "failed":
                stats["failed_downloads"] += count
                stats["platforms"][platform]["failed"] = count
                
            if result["avg_processing_time"]:
                stats["avg_processing_time"] = result["avg_processing_time"]
        
        stats["total_downloads"] = stats["successful_downloads"] + stats["failed_downloads"]
        
        return stats

class UserSettingsManager:
    def __init__(self):
        """Initialize settings manager with MongoDB connection"""
        self.db = db
        self._init_collections()

    def _init_collections(self):
        """Initialize MongoDB collections and indexes"""
        # Create indexes if they don't exist
        self.db.user_settings.create_index("user_id", unique=True)
        self.db.group_settings.create_index("group_id", unique=True)
        self.db.group_settings.create_index("admin_id")

    def get_settings(self, user_id: int, chat_id: Optional[int] = None, is_admin: bool = False) -> UserSettings:
        """
        Get settings based on context:
        - If chat_id is None, return user's personal settings
        - If chat_id is provided, return group settings if they exist, otherwise user's settings
        """
        try:
            # If this is a group chat
            if chat_id and chat_id < 0:  # Telegram group IDs are negative
                group_doc = self.db.group_settings.find_one({"group_id": chat_id})
                
                if group_doc:
                    return UserSettings(
                        user_id=user_id,
                        language=group_doc.get('language', 'en'),
                        default_quality=group_doc.get('default_quality', 'ask')
                    )
            
            # Get or create user settings
            user_doc = self.db.user_settings.find_one({"user_id": user_id})

            if not user_doc:
                # Create default settings
                settings = UserSettings(user_id=user_id)
                self.db.user_settings.insert_one({
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

    def update_settings(self, user_id: int, chat_id: Optional[int] = None, is_admin: bool = False, **kwargs) -> UserSettings:
        """Update settings based on context"""
        try:
            # If this is a group chat and user is admin
            if chat_id and chat_id < 0 and is_admin:
                valid_fields = {'language', 'default_quality'}
                update_fields = {k: v for k, v in kwargs.items() if k in valid_fields}
                
                if update_fields:
                    update_fields['updated_at'] = datetime.utcnow()
                    
                    self.db.group_settings.update_one(
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
                    
                    return self.get_settings(user_id, chat_id, is_admin)
            
            # Update user settings
            valid_fields = {'language', 'default_quality', 'username', 'first_name', 'last_name', 'phone_number', 'is_premium'}
            update_fields = {k: v for k, v in kwargs.items() if k in valid_fields}
            
            if update_fields:
                update_fields['updated_at'] = datetime.utcnow()
                
                self.db.user_settings.update_one(
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
            
            return self.get_settings(user_id)

        except Exception as e:
            logger.error(f"Failed to update settings for user {user_id}: {e}")
            return self.get_settings(user_id)

    def get_group_admin(self, group_id: int) -> Optional[int]:
        """Get the admin ID for a group if settings exist"""
        try:
            group_doc = self.db.group_settings.find_one({"group_id": group_id})
            return group_doc['admin_id'] if group_doc else None
        except Exception as e:
            logger.error(f"Failed to get admin for group {group_id}: {e}")
            return None
