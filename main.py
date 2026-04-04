from pathlib import Path
from dotenv import load_dotenv
import asyncio

# 🔥 Load env FIRST
load_dotenv(Path(__file__).parent / '.env')

from src.bot import ZenloadBot
from src.utils.pyro_client import app as pyro_app


def main():
    print("🟢 Bot is starting...")

    bot = ZenloadBot()

    # 🔥 Start Pyrogram SAFELY
    loop = asyncio.get_event_loop()
    loop.run_until_complete(pyro_app.start())

    print("🚀 Pyrogram started")

    # 🔥 Start Telegram bot
    bot.run()


if __name__ == "__main__":
    main()
