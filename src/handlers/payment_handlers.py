import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

class PaymentHandlers:
    def __init__(self, localization, settings_manager):
        self.localization = localization
        self.settings_manager = settings_manager

    async def get_message(self, user_id: int, key: str, **kwargs) -> str:
        """Get localized message - NOW ASYNC"""
        settings = await self.settings_manager.get_settings(user_id)
        return self.localization.get(settings.language, key, **kwargs)

    async def pre_checkout_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the pre-checkout callback"""
        query = update.pre_checkout_query
        await query.answer(ok=True)

    async def successful_payment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle successful payments"""
        payment = update.message.successful_payment
        if payment.invoice_payload == "donate_stars":
            # Await the localized success message
            success_msg = await self.get_message(update.effective_user.id, 'payment_success')
            await update.message.reply_text(success_msg)
