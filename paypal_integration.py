import paypalrestsdk
from datetime import datetime, timedelta
import env_config
import logging
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

# Configure PayPal SDK
paypalrestsdk.configure({
    "mode": env_config.PAYPAL_MODE,  # sandbox or live
    "client_id": env_config.PAYPAL_CLIENT_ID,
    "client_secret": env_config.PAYPAL_CLIENT_SECRET
})

class PayPalService:
    def __init__(self):
        paypalrestsdk.configure({
            "mode": env_config.PAYPAL_MODE,  # "sandbox" or "live"
            "client_id": env_config.PAYPAL_CLIENT_ID,
            "client_secret": env_config.PAYPAL_CLIENT_SECRET
        })
        # Don't cache ngrok_url - always get it fresh from env_config
        
    @property
    def ngrok_url(self):
        """Always get the current NGROK_URL from env_config"""
        return env_config.NGROK_URL
        
    def _get_plan_details(self, plan_type: str, sports: List[str] = None) -> Dict:
        """Get plan price and description based on plan type and sports"""
        if plan_type == 'basic':
            # Basic plan - single sport
            if sports and len(sports) == 1:
                sport = sports[0]
                if sport == 'tennis':
                    price = env_config.PRICE_TENNIS_MONTHLY
                elif sport == 'basketball':
                    price = env_config.PRICE_BASKETBALL_MONTHLY
                elif sport == 'handball':
                    price = env_config.PRICE_HANDBALL_MONTHLY
                else:
                    price = env_config.PRICE_BASIC_MONTHLY
            else:
                price = env_config.PRICE_BASIC_MONTHLY
            
            description = f"Basic Plan - {', '.join(sports) if sports else 'Single Sport'} (30 days)"
            
        elif plan_type == 'advanced':
            price = env_config.PRICE_ADVANCED_MONTHLY
            description = f"Advanced Plan - Multiple Sports (30 days)"
            
        elif plan_type == 'premium':
            price = env_config.PRICE_PREMIUM_MONTHLY
            description = "Premium Plan - All Sports Access (30 days)"
            
        elif plan_type == 'custom':
            # Custom plan - calculate based on selected sports
            price = 0
            if sports:
                for sport in sports:
                    if sport == 'tennis':
                        price += env_config.PRICE_TENNIS_MONTHLY * 0.8  # 20% discount for bundle
                    elif sport == 'basketball':
                        price += env_config.PRICE_BASKETBALL_MONTHLY * 0.8
                    elif sport == 'handball':
                        price += env_config.PRICE_HANDBALL_MONTHLY * 0.8
            
            description = f"Custom Plan - {', '.join(sports) if sports else 'Selected Sports'} (30 days)"
        
        else:
            price = env_config.PRICE_BASIC_MONTHLY
            description = "Standard Plan (30 days)"
            
        return {
            'price': round(price, 2),
            'description': description
        }
    
    def create_payment_new(self, user_id: str, plan_type: str, sports: List[str], duration: int, amount: float, description: str) -> Optional[Dict]:
        """Create PayPal payment with new pricing structure"""
        try:
            # Create payment object
            payment = paypalrestsdk.Payment({
                "intent": "sale",
                "payer": {
                    "payment_method": "paypal"
                },
                "redirect_urls": {
                    "return_url": f"{self.ngrok_url}/paypal/success",
                    "cancel_url": f"{self.ngrok_url}/paypal/cancel"
                },
                "transactions": [{
                    "item_list": {
                        "items": [{
                            "name": description,
                            "sku": f"{plan_type}_{duration}m",
                            "price": str(amount),
                            "currency": env_config.CURRENCY,
                            "quantity": 1
                        }]
                    },
                    "amount": {
                        "total": str(amount),
                        "currency": env_config.CURRENCY
                    },
                    "description": f"Premium Betting Analytics - {description}",
                    "custom": f"{user_id}|{plan_type}|{','.join(sports)}|{duration}"  # Store metadata
                }]
            })
            
            if payment.create():
                # Find approval URL
                approval_url = None
                for link in payment.links:
                    if link.rel == "approval_url":
                        approval_url = link.href
                        break
                
                logger.info(f"PayPal payment created successfully: {payment.id}")
                
                return {
                    'payment_id': payment.id,
                    'approval_url': approval_url,
                    'amount': amount,
                    'currency': env_config.CURRENCY,
                    'description': description
                }
            else:
                logger.error(f"PayPal payment creation failed: {payment.error}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating PayPal payment: {str(e)}")
            return None
    
    def create_payment(self, user_id: str, plan_type: str, sports: List[str]) -> Optional[Dict]:
        """Legacy method - kept for backward compatibility"""
        # Map old plan types to new structure
        if plan_type in ['tennis', 'basketball', 'handball']:
            new_plan_type = 'single_sport'
            price = env_config.PRICING['single_sport'][1]  # Default to 1 month
        elif plan_type == 'basic':
            new_plan_type = 'single_sport'
            price = env_config.PRICING['single_sport'][1]
        elif plan_type == 'advanced':
            new_plan_type = 'two_sports'
            price = env_config.PRICING['two_sports'][1]
        elif plan_type == 'premium':
            new_plan_type = 'full_access'
            price = env_config.PRICING['full_access'][1]
        else:
            new_plan_type = 'single_sport'
            price = env_config.PRICING['single_sport'][1]
        
        sport_names = {'tennis': 'Tennis', 'basketball': 'Basketball', 'handball': 'Handball'}
        sports_text = ", ".join([sport_names.get(sport, sport) for sport in sports])
        description = f"{new_plan_type.replace('_', ' ').title()} - {sports_text} - 1 Month"
        
        return self.create_payment_new(user_id, new_plan_type, sports, 1, price, description)
    
    def execute_payment(self, payment_id: str, payer_id: str) -> bool:
        """Execute PayPal payment after user approval"""
        try:
            payment = paypalrestsdk.Payment.find(payment_id)
            
            if payment.execute({"payer_id": payer_id}):
                logger.info(f"PayPal payment executed successfully: {payment_id}")
                return True
            else:
                logger.error(f"PayPal payment execution failed: {payment.error}")
                return False
                
        except Exception as e:
            logger.error(f"Error executing PayPal payment: {str(e)}")
            return False
    
    def get_payment_details(self, payment_id: str) -> Optional[Dict]:
        """Get payment details from PayPal"""
        try:
            payment = paypalrestsdk.Payment.find(payment_id)
            
            if payment:
                # Extract custom data
                custom_data = payment.transactions[0].custom if payment.transactions else ""
                user_id, plan_type, sports_str, duration = custom_data.split('|') if '|' in custom_data else ("", "", "", "1")
                
                return {
                    'payment_id': payment.id,
                    'status': payment.state,
                    'amount': float(payment.transactions[0].amount.total),
                    'currency': payment.transactions[0].amount.currency,
                    'user_id': user_id,
                    'plan_type': plan_type,
                    'sports': sports_str.split(',') if sports_str else [],
                    'duration_months': int(duration) if duration.isdigit() else 1,
                    'payer_email': payment.payer.payer_info.email if payment.payer.payer_info else None
                }
            else:
                return None
                
        except Exception as e:
            logger.error(f"Error getting payment details: {str(e)}")
            return None
    
    def create_refund(self, payment_id: str, amount: Optional[float] = None) -> bool:
        """Create a refund for a payment"""
        try:
            payment = paypalrestsdk.Payment.find(payment_id)
            
            # Get the sale transaction
            sale_id = None
            for transaction in payment.transactions:
                for related_resource in transaction.related_resources:
                    if hasattr(related_resource, 'sale'):
                        sale_id = related_resource.sale.id
                        break
            
            if not sale_id:
                logger.error("No sale transaction found for refund")
                return False
            
            sale = paypalrestsdk.Sale.find(sale_id)
            
            # Create refund
            refund_data = {}
            if amount:
                refund_data = {
                    "amount": {
                        "total": str(amount),
                        "currency": sale.amount.currency
                    }
                }
            
            refund = sale.refund(refund_data)
            
            if refund.success():
                logger.info(f"Refund created successfully for payment {payment_id}")
                return True
            else:
                logger.error(f"Refund creation failed: {refund.error}")
                return False
                
        except Exception as e:
            logger.error(f"Error creating refund: {str(e)}")
            return False

# Singleton instance
paypal_service = PayPalService() 