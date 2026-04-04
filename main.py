import logging
import asyncio
from pathlib import Path
from dotenv import load_dotenv

if __name__ == "__main__":
    load_dotenv(Path(__file__).parent / '.env')

    from src.bot import ZenloadBot
    from src.utils.pyro_client import app as pyro_app

    print("🟢 Bot is attempting to start...")

    async def start_pyro():
        await pyro_app.start()
        print("🚀 Pyrogram started")

    asyncio.run(start_pyro())

    # Run normal bot
    bot = ZenloadBot()
    bot.run()
