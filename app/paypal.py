import paypalrestsdk
from flask import Flask, request, jsonify
from threading import Thread
from app.config import Config, logger
from app.database import db_manager
from app.models import User, Payment
from sqlalchemy.exc import SQLAlchemyError

# Initialize Flask app for PayPal webhooks
paypal_app = Flask(__name__)

class PayPalManager:
    """
    Manages PayPal API interactions and Flask routes for payment processing.
    """
    def __init__(self):
        self.api = None
        self._initialize_paypal_sdk()

    def _initialize_paypal_sdk(self):
        """
        Initializes the PayPal REST SDK with credentials from Config.
        Ensures LIVE mode is used.
        """
        try:
            paypalrestsdk.configure({
                "mode": "live", # IMPORTANT: Ensure this is 'live' for production
                "client_id": Config.PAYPAL_CLIENT_ID,
                "client_secret": Config.PAYPAL_CLIENT_SECRET
            })
            self.api = paypalrestsdk.Api({
                "mode": "live",
                "client_id": Config.PAYPAL_CLIENT_ID,
                "client_secret": Config.PAYPAL_CLIENT_SECRET
            })
            logger.info("PayPal SDK initialized in LIVE mode.")
        except Exception as e:
            logger.critical(f"Failed to initialize PayPal SDK: {e}")
            raise

    def create_payment(self, amount, currency, description, return_url, cancel_url):
        """
        Creates a PayPal payment.
        """
        payment = paypalrestsdk.Payment({
            "intent": "sale",
            "payer": {
                "payment_method": "paypal"
            },
            "redirect_urls": {
                "return_url": return_url,
                "cancel_url": cancel_url
            },
            "transactions": [{
                "item_list": {
                    "items": [{
                        "name": description,
                        "sku": "item_sku", # Optional, but good for tracking
                        "price": str(amount),
                        "currency": currency,
                        "quantity": 1
                    }]
                },
                "amount": {
                    "total": str(amount),
                    "currency": currency
                },
                "description": description
            }]
        })

        if payment.create():
            logger.info(f"Payment created successfully: {payment.id}")
            return payment
        else:
            logger.error(f"Error creating payment: {payment.error}")
            return None

    def execute_payment(self, payment_id, payer_id):
        """
        Executes a PayPal payment.
        """
        payment = paypalrestsdk.Payment.find(payment_id)
        if payment.execute({"payer_id": payer_id}):
            logger.info(f"Payment {payment_id} executed successfully.")
            return payment
        else:
            logger.error(f"Error executing payment {payment_id}: {payment.error}")
            return None

paypal_manager = PayPalManager()

@paypal_app.route('/paypal/execute-payment', methods=['GET'])
def execute_payment_route():
    """
    Flask route to execute a PayPal payment after user approval.
    Expected query parameters: paymentId, PayerID, token, user_telegram_id
    """
    payment_id = request.args.get('paymentId')
    payer_id = request.args.get('PayerID')
    user_telegram_id = request.args.get('user_telegram_id') # Custom parameter to identify user

    if not all([payment_id, payer_id, user_telegram_id]):
        logger.warning("Missing parameters for payment execution.")
        return jsonify({"error": "Missing parameters"}), 400

    try:
        payment = paypal_manager.execute_payment(payment_id, payer_id)
        if payment and payment.state == 'approved':
            session = db_manager.get_session()
            try:
                user = session.query(User).filter_by(telegram_id=user_telegram_id).first()
                if user:
                    # Update the payment status in the database
                    db_payment = session.query(Payment).filter_by(paypal_payment_id=payment_id, user_id=user.id).first()
                    if db_payment:
                        db_payment.status = "COMPLETED"
                        session.add(db_payment)
                        session.commit()
                        logger.info(f"Payment {payment_id} for user {user_telegram_id} marked as COMPLETED in DB.")
                        return jsonify({"message": "Payment executed and recorded successfully", "status": "COMPLETED"}), 200
                    else:
                        logger.error(f"Payment {payment_id} not found in DB for user {user_telegram_id}.")
                        session.rollback()
                        return jsonify({"error": "Payment not found in database"}), 404
                else:
                    logger.error(f"User with telegram_id {user_telegram_id} not found in DB.")
                    session.rollback()
                    return jsonify({"error": "User not found"}), 404
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"Database error during payment execution for {payment_id}: {e}")
                return jsonify({"error": "Database error"}), 500
            finally:
                session.close()
        else:
            logger.error(f"Payment {payment_id} execution failed or not approved.")
            return jsonify({"error": "Payment execution failed"}), 500
    except Exception as e:
        logger.error(f"An unexpected error occurred during payment execution: {e}")
        return jsonify({"error": "Internal server error"}), 500

@paypal_app.route('/paypal/cancel-payment', methods=['GET'])
def cancel_payment_route():
    """
    Flask route for when a user cancels a PayPal payment.
    """
    payment_id = request.args.get('paymentId')
    user_telegram_id = request.args.get('user_telegram_id')

    logger.info(f"Payment {payment_id} cancelled by user {user_telegram_id}.")

    session = db_manager.get_session()
    try:
        user = session.query(User).filter_by(telegram_id=user_telegram_id).first()
        if user:
            db_payment = session.query(Payment).filter_by(paypal_payment_id=payment_id, user_id=user.id).first()
            if db_payment:
                db_payment.status = "CANCELLED"
                session.add(db_payment)
                session.commit()
                logger.info(f"Payment {payment_id} for user {user_telegram_id} marked as CANCELLED in DB.")
            else:
                logger.warning(f"Cancelled payment {payment_id} not found in DB for user {user_telegram_id}.")
        else:
            logger.warning(f"User with telegram_id {user_telegram_id} not found for cancelled payment {payment_id}.")
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Database error during payment cancellation for {payment_id}: {e}")
    finally:
        session.close()

    return jsonify({"message": "Payment cancelled"}), 200

def run_flask_app():
    """
    Runs the Flask application.
    """
    try:
        # Use Gunicorn for production deployment, but for local testing, Flask's dev server is fine.
        # For actual deployment, Gunicorn will be managed by PM2 or systemd.
        logger.info(f"Starting Flask app on port {Config.FLASK_PORT}...")
        paypal_app.run(host='0.0.0.0', port=Config.FLASK_PORT, debug=False)
    except Exception as e:
        logger.critical(f"Flask app failed to start: {e}")
        raise

def start_flask_thread():
    """
    Starts the Flask application in a separate thread.
    """
    flask_thread = Thread(target=run_flask_app)
    flask_thread.daemon = True # Allow main program to exit even if thread is running
    flask_thread.start()
    logger.info("Flask app thread started.")
    return flask_thread
