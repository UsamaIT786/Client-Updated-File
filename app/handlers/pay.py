from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler
from app.config import Config, logger
from app.paypal import paypal_manager
from app.database import db_manager
from app.models import User, Payment
from sqlalchemy.exc import SQLAlchemyError

async def pay_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Initiates a PayPal payment process.
    """
    user_telegram_id = update.effective_user.id
    session = db_manager.get_session()
    try:
        user = session.query(User).filter_by(telegram_id=user_telegram_id).first()
        if not user:
            user = User(telegram_id=user_telegram_id, username=update.effective_user.username)
            session.add(user)
            session.commit()
            logger.info(f"New user {user_telegram_id} registered during pay command.")

        amount = 10.00 # Example amount, can be dynamic
        currency = "USD"
        description = "Satta AI Bot Service"

        # Construct return and cancel URLs for PayPal
        # IMPORTANT: Replace with your actual public domain/IP
        base_url = "YOUR_PUBLIC_DOMAIN_OR_IP"
        return_url = f"{base_url}/paypal/execute-payment?user_telegram_id={user_telegram_id}"
        cancel_url = f"{base_url}/paypal/cancel-payment?user_telegram_id={user_telegram_id}"

        payment = paypal_manager.create_payment(amount, currency, description, return_url, cancel_url)

        if payment:
            # Save payment details to database
            db_payment = Payment(
                user_id=user.id,
                paypal_payment_id=payment.id,
                amount=amount,
                currency=currency,
                status="CREATED"
            )
            session.add(db_payment)
            session.commit()
            logger.info(f"Payment {payment.id} created in DB for user {user_telegram_id}.")

            for link in payment.links:
                if link.rel == "approval_url":
                    approval_url = link.href
                    keyboard = [[InlineKeyboardButton("Pay with PayPal", url=approval_url)]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text(
                        "Please click the button below to complete your payment:",
                        reply_markup=reply_markup
                    )
                    logger.info(f"Sent PayPal approval URL to user {user_telegram_id}.")
                    return
            await update.message.reply_text("Could not get PayPal approval URL. Please try again.")
        else:
            await update.message.reply_text("Failed to create PayPal payment. Please try again later.")
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Database error during pay command for user {user_telegram_id}: {e}")
        await update.message.reply_text("A database error occurred. Please try again later.")
    except Exception as e:
        logger.error(f"Error in pay_command for user {user_telegram_id}: {e}")
        await update.message.reply_text("An unexpected error occurred. Please try again later.")
    finally:
        session.close()

pay_handler = CommandHandler("pay", pay_command)
