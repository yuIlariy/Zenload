from pathlib import Path
from dotenv import load_dotenv

# Load env first
load_dotenv(Path(__file__).parent / '.env')

from src.bot import ZenloadBot


def main():
    print("🟢 Bot is starting...")

    bot = ZenloadBot()
    bot.run()


if __name__ == "__main__":
    main()
