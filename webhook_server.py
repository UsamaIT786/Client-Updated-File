from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import logging
import asyncio
import requests
from database import SessionLocal, Payment, User, Subscription
from paypal_integration import paypal_service
import env_config

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_telegram_message(user_telegram_id: str, message: str):
    """Send a message to user via Telegram Bot API"""
    try:
        url = f"https://api.telegram.org/bot{env_config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': user_telegram_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"Payment notification sent to user {user_telegram_id}")
            return True
        else:
            logger.error(f"Failed to send notification to user {user_telegram_id}: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending Telegram notification: {str(e)}")
        return False

@app.route('/paypal/success')
def paypal_success():
    """Handle successful PayPal payment"""
    payment_id = request.args.get('paymentId')
    payer_id = request.args.get('PayerID')
    
    if not payment_id or not payer_id:
        return "Missing payment parameters", 400
    
    # Execute payment
    if paypal_service.execute_payment(payment_id, payer_id):
        # Get payment details
        payment_details = paypal_service.get_payment_details(payment_id)
        
        if payment_details:
            db = SessionLocal()
            try:
                # Update payment status
                payment = db.query(Payment).filter_by(paypal_payment_id=payment_id).first()
                if payment:
                    payment.status = 'completed'
                    payment.updated_at = datetime.utcnow()
                    
                    # Get user details
                    user = db.query(User).filter_by(id=payment.user_id).first()
                    
                    # Create subscription with proper duration
                    duration_months = payment.duration_months or 1
                    end_date = datetime.utcnow() + timedelta(days=30 * duration_months)
                    
                    subscription = Subscription(
                        user_id=payment.user_id,
                        plan_type=payment.plan_type,
                        sports=payment.sports,
                        start_date=datetime.utcnow(),
                        end_date=end_date,
                        is_active=True,
                        duration_months=duration_months
                    )
                    
                    db.add(subscription)
                    db.commit()
                    
                    logger.info(f"Payment {payment_id} completed and subscription created for user {payment.user_id}")
                    
                    # Send success notification to user
                    if user:
                        sport_names = {'tennis': 'Tennis', 'basketball': 'Basketball', 'handball': 'Handball'}
                        sports_text = ", ".join([sport_names.get(sport, sport.title()) for sport in payment.sports])
                        
                        plan_names = {
                            'single_sport': '1 Sport',
                            'two_sports': '2 Combined Sports',
                            'full_access': 'Full Access (All 3 Sports)'
                        }
                        plan_name = plan_names.get(payment.plan_type, payment.plan_type.title())
                        
                        success_message = f"""
🎉 **Payment Successful!**

✅ **Subscription Activated**

**Plan**: {plan_name}
**Sports**: {sports_text}
**Duration**: {duration_months} month{'s' if duration_months > 1 else ''}
**Amount**: €{payment.amount}
**Valid Until**: {end_date.strftime('%Y-%m-%d')}

🚨 **You will now receive notifications when favorites are trailing at halftime!**

Thank you for subscribing to Premium Betting Analytics! 🎯
"""
                        
                        send_telegram_message(user.telegram_id, success_message)
                    
                    return f"""
                    <html>
                        <head><title>Payment Successful</title></head>
                        <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                            <h2 style="color: green;">✅ Payment Successful!</h2>
                            <p>Your subscription has been activated.</p>
                            <p><strong>Plan:</strong> {payment.plan_type.replace('_', ' ').title()}</p>
                            <p><strong>Duration:</strong> {duration_months} month{'s' if duration_months > 1 else ''}</p>
                            <p><strong>Amount:</strong> €{payment.amount}</p>
                            <p><strong>📱 A confirmation has been sent to your Telegram!</strong></p>
                            <p>You can now return to Telegram to start receiving notifications!</p>
                            <script>
                                setTimeout(function() {{
                                    window.close();
                                }}, 5000);
                            </script>
                        </body>
                    </html>
                    """
                    
            except Exception as e:
                logger.error(f"Error processing successful payment: {str(e)}")
                db.rollback()
                
                # Send error notification to user if we have user info
                try:
                    payment = db.query(Payment).filter_by(paypal_payment_id=payment_id).first()
                    if payment:
                        user = db.query(User).filter_by(id=payment.user_id).first()
                        if user:
                            error_message = f"""
❌ **Payment Processing Error**

Your PayPal payment was successful, but there was an issue activating your subscription.

**Payment ID**: {payment_id}

Please contact support with this payment ID. We will resolve this quickly!

Sorry for the inconvenience. 🙏
"""
                            send_telegram_message(user.telegram_id, error_message)
                except:
                    pass  # Don't let notification errors crash the webhook
                
                return "Error processing payment", 500
            finally:
                db.close()
    
    # Payment execution failed
    db = SessionLocal()
    try:
        # Try to notify user of failure
        payment = db.query(Payment).filter_by(paypal_payment_id=payment_id).first()
        if payment:
            user = db.query(User).filter_by(id=payment.user_id).first()
            if user:
                failure_message = f"""
❌ **Payment Failed**

Unfortunately, your payment could not be processed.

**Payment ID**: {payment_id}

Please try again or contact support if you continue to have issues.

Your payment method has not been charged.
"""
                send_telegram_message(user.telegram_id, failure_message)
    except:
        pass  # Don't let notification errors crash the webhook
    finally:
        db.close()
    
    return "Payment execution failed", 400

@app.route('/paypal/cancel')
def paypal_cancel():
    """Handle cancelled PayPal payment"""
    payment_id = request.args.get('paymentId')
    
    # Try to notify user of cancellation
    if payment_id:
        db = SessionLocal()
        try:
            payment = db.query(Payment).filter_by(paypal_payment_id=payment_id).first()
            if payment:
                user = db.query(User).filter_by(id=payment.user_id).first()
                if user:
                    cancel_message = f"""
⚠️ **Payment Cancelled**

Your payment was cancelled before completion.

No charges have been made to your payment method.

You can try again anytime by using the /start command and selecting a subscription plan.

Thank you for considering Premium Betting Analytics! 🎯
"""
                    send_telegram_message(user.telegram_id, cancel_message)
        except Exception as e:
            logger.error(f"Error sending cancellation notification: {str(e)}")
        finally:
            db.close()
    
    return f"""
    <html>
        <head><title>Payment Cancelled</title></head>
        <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
            <h2 style="color: orange;">⚠️ Payment Cancelled</h2>
            <p>Your payment was cancelled. You can return to Telegram to try again.</p>
            <p><strong>📱 A notification has been sent to your Telegram!</strong></p>
            <script>
                setTimeout(function() {{
                    window.close();
                }}, 3000);
            </script>
        </body>
    </html>
    """

@app.route('/paypal/webhook', methods=['POST'])
def paypal_webhook():
    """Handle PayPal IPN/webhook notifications"""
    try:
        data = request.json
        logger.info(f"Received PayPal webhook: {data}")
        
        # Handle different webhook events
        event_type = data.get('event_type', '')
        
        if event_type == 'PAYMENT.SALE.COMPLETED':
            # Handle completed payment
            resource = data.get('resource', {})
            payment_id = resource.get('parent_payment', '')
            
            if payment_id:
                # Update payment status in database
                db = SessionLocal()
                try:
                    payment = db.query(Payment).filter_by(paypal_payment_id=payment_id).first()
                    if payment and payment.status == 'pending':
                        payment.status = 'completed'
                        payment.updated_at = datetime.utcnow()
                        db.commit()
                        logger.info(f"Payment {payment_id} marked as completed via webhook")
                        
                        # Send webhook completion notification to user
                        user = db.query(User).filter_by(id=payment.user_id).first()
                        if user:
                            webhook_message = f"""
🔔 **Payment Confirmed via PayPal Webhook**

Your payment has been verified and confirmed by PayPal.

**Payment ID**: {payment_id}
**Status**: ✅ Completed

Your subscription is now fully active!
"""
                            send_telegram_message(user.telegram_id, webhook_message)
                        
                finally:
                    db.close()
        
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"Error processing PayPal webhook: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'PayPal Webhook Server'
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True) 