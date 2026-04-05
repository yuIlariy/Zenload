from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from typing import Optional


class KeyboardBuilder:
    def __init__(self, localization, settings_manager):
        self.localization = localization
        self.settings_manager = settings_manager

    async def get_message(self, user_id: int, key: str, chat_id: Optional[int] = None, is_admin: bool = False, **kwargs) -> str:
        """Get localized message"""
        settings = await self.settings_manager.get_settings(user_id, chat_id, is_admin)
        return self.localization.get(settings.language, key, **kwargs)

    async def build_main_keyboard(self, user_id: int) -> ReplyKeyboardMarkup:
        """Main keyboard (private chat only)"""
        btn_settings = await self.get_message(user_id, 'btn_settings')
        btn_help = await self.get_message(user_id, 'btn_help')
        btn_donate = await self.get_message(user_id, 'btn_donate')

        keyboard = [
            [
                KeyboardButton(btn_settings),
                KeyboardButton(btn_help),
                KeyboardButton(btn_donate)
            ]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    async def build_welcome_keyboard(self, user_id: int, chat_id: Optional[int] = None, is_admin: bool = False) -> InlineKeyboardMarkup:
        """Welcome keyboard"""
        btn_updates = await self.get_message(user_id, 'btn_updates', chat_id, is_admin)

        keyboard = [
            [InlineKeyboardButton(btn_updates, url="https://t.me/OtherBs")]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def build_settings_keyboard(self, user_id: int, chat_id: Optional[int] = None, is_admin: bool = False) -> InlineKeyboardMarkup:
        """Settings menu"""
        context = f":{chat_id}" if chat_id and chat_id < 0 else ""

        btn_lang = await self.get_message(user_id, 'btn_language', chat_id, is_admin)
        btn_qual = await self.get_message(user_id, 'btn_quality', chat_id, is_admin)

        keyboard = [
            [
                InlineKeyboardButton(btn_lang, callback_data=f"settings:language{context}"),
                InlineKeyboardButton(btn_qual, callback_data=f"settings:quality{context}")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def build_language_keyboard(self, user_id: int, chat_id: Optional[int] = None, is_admin: bool = False) -> InlineKeyboardMarkup:
        """Language selection"""
        context = f":{chat_id}" if chat_id and chat_id < 0 else ""

        btn_ru = await self.get_message(user_id, 'btn_russian', chat_id, is_admin)
        btn_en = await self.get_message(user_id, 'btn_english', chat_id, is_admin)
        btn_back = await self.get_message(user_id, 'btn_back', chat_id, is_admin)

        keyboard = [
            [
                InlineKeyboardButton(btn_ru, callback_data=f"set_lang:ru{context}"),
                InlineKeyboardButton(btn_en, callback_data=f"set_lang:en{context}")
            ],
            [InlineKeyboardButton(btn_back, callback_data=f"settings:back{context}")]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def build_quality_keyboard(self, user_id: int, chat_id: Optional[int] = None, is_admin: bool = False) -> InlineKeyboardMarkup:
        """Default quality settings (NOW WITH AUDIO)"""
        context = f":{chat_id}" if chat_id and chat_id < 0 else ""

        btn_ask = await self.get_message(user_id, 'btn_ask', chat_id, is_admin)
        btn_best = await self.get_message(user_id, 'btn_best', chat_id, is_admin)
        btn_back = await self.get_message(user_id, 'btn_back', chat_id, is_admin)

        keyboard = [
            [InlineKeyboardButton(btn_ask, callback_data=f"set_quality:ask{context}")],
            [InlineKeyboardButton(btn_best, callback_data=f"set_quality:best{context}")],
            [InlineKeyboardButton("🎵 Audio (MP3)", callback_data=f"set_quality:audio{context}")],
            [InlineKeyboardButton(btn_back, callback_data=f"settings:back{context}")]
        ]

        return InlineKeyboardMarkup(keyboard)

    async def build_format_selection_keyboard(self, user_id: int, formats: list, chat_id: Optional[int] = None, is_admin: bool = False) -> InlineKeyboardMarkup:
        """Download format selection (NOW WITH AUDIO)"""
        context = f":{chat_id}" if chat_id and chat_id < 0 else ""
        keyboard = []

        # 🎬 Video formats (dynamic)
        for fmt in formats:
            btn_text = await self.get_message(
                user_id,
                'quality_format',
                chat_id,
                is_admin,
                quality=fmt['quality'],
                ext=fmt['ext']
            )
            keyboard.append([
                InlineKeyboardButton(btn_text, callback_data=f"quality:{fmt['id']}{context}")
            ])

        # 🎵 Audio option (always present)
        keyboard.append([
            InlineKeyboardButton("🎵 Audio (MP3)", callback_data=f"quality:audio{context}")
        ])

        # ⭐ Best fallback
        btn_best = await self.get_message(user_id, 'best_quality', chat_id, is_admin)
        keyboard.append([
            InlineKeyboardButton(btn_best, callback_data=f"quality:best{context}")
        ])

        return InlineKeyboardMarkup(keyboard)
