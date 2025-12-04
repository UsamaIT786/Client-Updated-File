from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from app.config import Config, logger
from app.database import db_manager
from app.models import User
from sqlalchemy.exc import SQLAlchemyError
import asyncio

class TelegramBot:
    """
    Manages the Telegram bot's lifecycle, handlers, and error handling.
    """
    def __init__(self):
        self.application = None

    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log the error and send a message to the user."""
        logger.error(f"Exception while handling an update: {context.error}", exc_info=True)
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "An error occurred while processing your request. Please try again later."
                )
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")

    async def _register_user_if_not_exists(self, update: Update) -> User:
        """
        Registers a new user in the database if they don't already exist.
        Returns the User object.
        """
        session = db_manager.get_session()
        try:
            telegram_id = update.effective_user.id
            username = update.effective_user.username
            first_name = update.effective_user.first_name
            last_name = update.effective_user.last_name

            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if not user:
                user = User(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name
                )
                session.add(user)
                session.commit()
                logger.info(f"New user registered: {username} ({telegram_id})")
            return user
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Database error during user registration: {e}")
            raise
        finally:
            session.close()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Sends a welcome message when the command /start is issued."""
        try:
            user = await self._register_user_if_not_exists(update)
            await update.message.reply_text(
                f"Hello {user.first_name}! Welcome to the Satta AI Bot. "
                "Use /pay to make a payment or /help for more options."
            )
            logger.info(f"User {user.telegram_id} used /start command.")
        except Exception as e:
            logger.error(f"Error in start_command for user {update.effective_user.id}: {e}")
            await update.message.reply_text("Failed to process your request. Please try again.")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Sends a help message when the command /help is issued."""
        await update.message.reply_text("Available commands:\n"
                                        "/start - Start the bot\n"
                                        "/pay - Make a payment\n"
                                        "/help - Show this help message")
        logger.info(f"User {update.effective_user.id} used /help command.")

    async def unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Responds to unknown commands."""
        await update.message.reply_text("Sorry, I don't understand that command.")
        logger.warning(f"User {update.effective_user.id} sent unknown command: {update.message.text}")

    def run_polling(self):
        """
        Starts the bot in long-polling mode.
        Ensures stability with error handling and restart mechanisms.
        """
        self.application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()

        # Register handlers
        from app.handlers.start import start_handler
        from app.handlers.pay import pay_handler

        self.application.add_handler(start_handler)
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(pay_handler)
        self.application.add_handler(MessageHandler(filters.COMMAND, self.unknown_command))

        # Register error handler
        self.application.add_error_handler(self._error_handler)

        logger.info("Starting Telegram bot in polling mode...")
        # Run the bot until the user presses Ctrl-C or the process receives SIGINT, SIGTERM or SIGABRT.
        # This should be used for production, as it handles restarts and keeps polling stable.
        self.application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

    def start_bot_thread(self):
        """
        Starts the Telegram bot in a separate thread.
        """
        # Use asyncio.run to run the polling application in a separate thread
        # This is necessary because run_polling is a blocking call
        def run_bot_loop():
            try:
                self.run_polling()
            except Exception as e:
                logger.critical(f"Telegram bot polling failed: {e}")
                # Implement a robust restart mechanism if needed, e.g., using a process manager

        import threading
        bot_thread = threading.Thread(target=run_bot_loop)
        bot_thread.daemon = True # Allow main program to exit even if thread is running
        bot_thread.start()
        logger.info("Telegram bot thread started.")
        return bot_thread

# Initialize the bot
telegram_bot = TelegramBot()
