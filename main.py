from pathlib import Path
from dotenv import load_dotenv

# 🔥 LOAD ENV FIRST
load_dotenv(Path(__file__).parent / '.env')

from src.bot import ZenloadBot
from src.utils.pyro_client import app as pyro_app


def main():
    print("🟢 Bot is starting...")

    # 🔥 Start Pyrogram SYNCHRONOUSLY (IMPORTANT)
    pyro_app.start()
    print("🚀 Pyrogram started")

    # 🔥 Start bot (it manages its own loop)
    bot = ZenloadBot()
    bot.run()


if __name__ == "__main__":
    main()
