import os
import logging
from dotenv import load_dotenv
from colorlog import ColoredFormatter

# Load environment variables from .env file
load_dotenv()

class Config:
    """
    Configuration class to manage environment variables and application settings.
    """
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
    PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET")
    DB_URI = os.getenv("DB_URI")
    FLASK_PORT = int(os.getenv("FLASK_PORT", 5000))
    BOT_MODE = os.getenv("BOT_MODE", "polling") # "polling" or "webhook"

    # Ensure all critical environment variables are set
    REQUIRED_ENV_VARS = [
        "TELEGRAM_BOT_TOKEN",
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "DB_URI",
    ]

    @classmethod
    def validate_env(cls):
        for var in cls.REQUIRED_ENV_VARS:
            if not getattr(cls, var):
                raise ValueError(f"Missing required environment variable: {var}")

def setup_logging():
    """
    Sets up a clean and colored logging system for the application.
    """
    formatter = ColoredFormatter(
        "%(log_color)s%(levelname)-8s%(reset)s %(white)s%(message)s",
        datefmt=None,
        reset=True,
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        },
        secondary_log_colors={},
        style='%'
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logger = logging.getLogger()
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    logger.addHandler(handler)

    # Suppress verbose logging from other libraries
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)

    return logger

# Initialize logging
logger = setup_logging()

# Validate environment variables on startup
try:
    Config.validate_env()
    logger.info("Environment variables loaded and validated successfully.")
except ValueError as e:
    logger.critical(f"Configuration Error: {e}")
    exit(1) # Exit if critical environment variables are missing
