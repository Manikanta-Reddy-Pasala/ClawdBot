import os
from dotenv import load_dotenv

load_dotenv(os.environ.get("ENV_FILE", ".env"))


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

    DEFAULT_CONTEXT_NAME: str = os.environ.get("DEFAULT_CONTEXT_NAME", "vm")
    DEFAULT_WORKING_DIR: str = os.environ.get("DEFAULT_WORKING_DIR", "/opt/clawdbot")

    # DevOps API server
    API_PORT: int = int(os.environ.get("API_PORT", "8000"))
    API_KEY: str = os.environ.get("DEVOPS_API_KEY", "")

    # Telegram chat ID for DevOps alerts (set to your chat ID)
    ALERT_CHAT_ID: int = int(os.environ.get("ALERT_CHAT_ID", "0"))

    # Enable DevOps monitoring (requires kubectl access)
    DEVOPS_ENABLED: bool = os.environ.get("DEVOPS_ENABLED", "true").lower() == "true"


config = Config()
