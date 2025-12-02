import paypalrestsdk, os
from dotenv import load_dotenv
import logging
import json

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

paypalrestsdk.configure({
    "mode": os.getenv("PAYPAL_MODE"),
    "client_id": os.getenv("PAYPAL_CLIENT_ID"),
    "client_secret": os.getenv("PAYPAL_CLIENT_SECRET")
})

def create_payment(amount, currency="EUR"):
    """
    Creates a PayPal payment.
    """
    payment = paypalrestsdk.Payment({
        "intent": "sale",
        "payer": {
            "payment_method": "paypal"
        },
        "redirect_urls": {
            "return_url": os.getenv("BASE_URL") + "/paypal/execute",
            "cancel_url": os.getenv("BASE_URL") + "/paypal/cancel"
        },
        "transactions": [{
            "item_list": {
                "items": [{
                    "name": "Subscription",
                    "sku": "item",
                    "price": str(amount),
                    "currency": currency,
                    "quantity": "1"
                }]
            },
            "amount": {
                "total": str(amount),
                "currency": currency
            },
            "description": "Subscription Payment"
        }]
    })

    try:
        if payment.create():
            logging.info(f"Payment created successfully: {payment.id}")
            for link in payment.links:
                if link.rel == "approval_url":
                    approval_url = str(link.href)
                    return {"success": True, "approval_url": approval_url, "payment_id": payment.id}
        else:
            logging.error(f"Error creating payment: {payment.error}")
            return {"success": False, "message": payment.error}
    except Exception as e:
        logging.error(f"Exception during payment creation: {e}")
        return {"success": False, "message": str(e)}

def execute_payment(payment_id, payer_id):
    """
    Executes a PayPal payment.
    """
    payment = paypalrestsdk.Payment.find(payment_id)

    try:
        if payment.execute({"payer_id": payer_id}):
            logging.info(f"Payment {payment_id} executed successfully.")
            return {"success": True, "message": "Payment executed successfully", "transaction": payment.to_dict(), "status": payment.state}
        else:
            logging.error(f"Error executing payment {payment_id}: {payment.error}")
            return {"success": False, "message": payment.error, "transaction": None, "status": payment.state}
    except Exception as e:
        logging.error(f"Exception during payment execution for {payment_id}: {e}")
        return {"success": False, "message": str(e), "transaction": None, "status": "error"}
