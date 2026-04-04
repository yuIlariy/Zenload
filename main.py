import asyncio
from pathlib import Path
from dotenv import load_dotenv

# 🔥 LOAD ENV FIRST (VERY IMPORTANT)
load_dotenv(Path(__file__).parent / '.env')

from src.bot import ZenloadBot
from src.utils.pyro_client import app as pyro_app


async def main():
    print("🟢 Bot is starting...")

    await pyro_app.start()
    print("🚀 Pyrogram started")

    bot = ZenloadBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
