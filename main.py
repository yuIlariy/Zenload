import logging
from pathlib import Path
from dotenv import load_dotenv

if __name__ == "__main__":
    # Load environment variables from .env file
    load_dotenv(Path(__file__).parent / '.env')
    from src.bot import ZenloadBot
    
    # Initialize and run the bot
    print("🟢 Bot is attempting to start... If it fails, the exact error will print below:")
    bot = ZenloadBot()
    bot.run()
