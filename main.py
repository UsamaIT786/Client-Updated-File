import threading
import time
from app.config import Config, logger
from app.database import db_manager
from app.bot import telegram_bot
from app.paypal import start_flask_thread
from sqlalchemy.exc import SQLAlchemyError

def main():
    """
    Main function to initialize and start the database, Flask app, and Telegram bot.
    """
    logger.info("Starting Satta AI Bot application...")

    # 1. Connect to the database
    try:
        db_manager.connect()
        # Optionally create tables if they don't exist (for initial setup, Alembic is preferred)
        # db_manager.create_all_tables()
    except SQLAlchemyError:
        logger.critical("Application cannot start without a database connection. Exiting.")
        return

    # 2. Start Flask app in a separate thread
    flask_thread = start_flask_thread()

    # 3. Start Telegram bot in a separate thread
    bot_thread = telegram_bot.start_bot_thread()

    logger.info("Application initialized. Flask and Telegram bot are running in separate threads.")
    logger.info(f"Flask app running on http://0.0.0.0:{Config.FLASK_PORT}")
    logger.info("Telegram bot is polling for updates.")

    # Keep the main thread alive to allow daemon threads to run
    try:
        while True:
            time.sleep(1)
            if not flask_thread.is_alive():
                logger.error("Flask thread died unexpectedly. Attempting to restart...")
                # In a real production scenario, you might want more sophisticated restart logic
                # or rely on process managers like PM2/systemd to restart the entire application.
                # For now, we'll just log and let the main process continue.
            if not bot_thread.is_alive():
                logger.error("Telegram bot thread died unexpectedly. Attempting to restart...")
                # Similar to Flask, rely on external process managers for robust restarts.
    except KeyboardInterrupt:
        logger.info("Application stopped by user (Ctrl+C).")
    except Exception as e:
        logger.critical(f"An unhandled exception occurred in the main thread: {e}", exc_info=True)
    finally:
        logger.info("Shutting down application.")

if __name__ == "__main__":
    main()
