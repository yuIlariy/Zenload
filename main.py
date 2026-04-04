from pathlib import Path
from dotenv import load_dotenv
import asyncio

# 🔥 LOAD ENV FIRST
load_dotenv(Path(__file__).parent / '.env')

from src.bot import ZenloadBot
from src.utils.pyro_client import app as pyro_app


def main():
    print("🟢 Bot is starting...")

    bot = ZenloadBot()

    # 🔥 Get telegram's loop
    loop = asyncio.get_event_loop()

    # 🔥 Start Pyrogram in SAME loop
    loop.create_task(pyro_app.start())
    print("🚀 Pyrogram scheduled")

    # 🔥 Run telegram bot (it controls loop)
    bot.run()


if __name__ == "__main__":
    main()
