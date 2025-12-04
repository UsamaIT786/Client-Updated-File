from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from app.config import logger
from app.bot import telegram_bot # Import the bot instance to access _register_user_if_not_exists

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the command /start is issued."""
    try:
        user = await telegram_bot._register_user_if_not_exists(update)
        await update.message.reply_text(
            f"Hello {user.first_name}! Welcome to the Satta AI Bot. "
            "Use /pay to make a payment or /help for more options."
        )
        logger.info(f"User {user.telegram_id} used /start command.")
    except Exception as e:
        logger.error(f"Error in start_command for user {update.effective_user.id}: {e}")
        await update.message.reply_text("Failed to process your request. Please try again.")

start_handler = CommandHandler("start", start_command)
