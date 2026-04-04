import asyncio
from pathlib import Path
from dotenv import load_dotenv

from src.bot import ZenloadBot
from src.utils.pyro_client import app as pyro_app


async def start_pyro():
    await pyro_app.start()
    print("🚀 Pyrogram started")


if __name__ == "__main__":
    load_dotenv(Path(__file__).parent / '.env')

    print("🟢 Bot is starting...")

    # Start Pyrogram in background loop
    loop = asyncio.get_event_loop()
    loop.create_task(start_pyro())

    bot = ZenloadBot()
    bot.run()
