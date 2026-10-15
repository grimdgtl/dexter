import os

# Testovi ne smeju da zavise od pravog .env-a ni od mreže.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("TELEGRAM_OWNER_CHAT_ID", "1")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
