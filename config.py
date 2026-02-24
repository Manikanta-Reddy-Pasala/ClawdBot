import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]

    # Comma-separated list of allowed Telegram user IDs
    ALLOWED_USER_IDS: set[int] = {
        int(uid.strip())
        for uid in os.environ.get("ALLOWED_USER_IDS", "").split(",")
        if uid.strip()
    }

    CONTEXT_WINDOW: int = int(os.environ.get("CONTEXT_WINDOW", "20"))

    SHELL_TIMEOUT: int = int(os.environ.get("SHELL_TIMEOUT", "60"))
    SHELL_MAX_OUTPUT: int = int(os.environ.get("SHELL_MAX_OUTPUT", "4000"))

    DB_PATH: str = os.environ.get("DB_PATH", "/opt/clawdbot/conversations.db")
    REPOS_DIR: str = os.environ.get("REPOS_DIR", "/opt/clawdbot/repos")


config = Config()
