import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def reload_env():
    """Reload environment variables from .env file"""
    global NGROK_URL, API_TOKEN, TELEGRAM_BOT_TOKEN, PREMIUM_CHANNEL_ID, FREE_CHANNEL_ID
    global PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_MODE, DATABASE_URL, ADMIN_TELEGRAM_ID
    
    # Reload the .env file
    load_dotenv(override=True)
    
    # Update all globals
    NGROK_URL = os.getenv('NGROK_URL', 'https://your-ngrok-url.ngrok.io')
    API_TOKEN = os.getenv('API_TOKEN', '215845-ME7THuixJ1hOxE')
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN')
    PREMIUM_CHANNEL_ID = os.getenv('PREMIUM_CHANNEL_ID', '@your_premium_channel')
    FREE_CHANNEL_ID = os.getenv('FREE_CHANNEL_ID', '@your_free_channel')
    PAYPAL_CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID', 'YOUR_PAYPAL_SANDBOX_CLIENT_ID')
    PAYPAL_CLIENT_SECRET = os.getenv('PAYPAL_CLIENT_SECRET', 'YOUR_PAYPAL_SANDBOX_CLIENT_SECRET')
    PAYPAL_MODE = os.getenv('PAYPAL_MODE', 'sandbox')
    DATABASE_URL = os.getenv('BOT_DATABASE_URL', 'sqlite:///betting_bot.db')
    ADMIN_TELEGRAM_ID = os.getenv('ADMIN_TELEGRAM_ID', 'YOUR_ADMIN_TELEGRAM_ID')

# Bet365 API Configuration
API_TOKEN = os.getenv('API_TOKEN', '215845-ME7THuixJ1hOxE')

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN')
PREMIUM_CHANNEL_ID = os.getenv('PREMIUM_CHANNEL_ID', '@your_premium_channel')
FREE_CHANNEL_ID = os.getenv('FREE_CHANNEL_ID', '@your_free_channel')

# PayPal Sandbox Configuration
PAYPAL_CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID', 'YOUR_PAYPAL_SANDBOX_CLIENT_ID')
PAYPAL_CLIENT_SECRET = os.getenv('PAYPAL_CLIENT_SECRET', 'YOUR_PAYPAL_SANDBOX_CLIENT_SECRET')
PAYPAL_MODE = os.getenv('PAYPAL_MODE', 'sandbox')

# Ngrok Configuration
NGROK_URL = os.getenv('NGROK_URL', 'https://your-ngrok-url.ngrok.io')

# Database Configuration - Force SQLite for local development
DATABASE_URL = os.getenv('BOT_DATABASE_URL', 'sqlite:///betting_bot.db')
# Use BOT_DATABASE_URL instead of DATABASE_URL to avoid conflicts with system env vars

# Admin Configuration
ADMIN_TELEGRAM_ID = os.getenv('ADMIN_TELEGRAM_ID', 'YOUR_ADMIN_TELEGRAM_ID')

# New Subscription Pricing Structure (in EUR)
PRICING = {
    # 1 Sport (Basketball/Handball/Tennis)
    'single_sport': {
        1: 120.0,   # 1 month
        3: 300.0,   # 3 months  
        6: 500.0    # 6 months
    },
    # 2 Combined Sports
    'two_sports': {
        1: 180.0,   # 1 month
        3: 450.0,   # 3 months
        6: 750.0    # 6 months
    },
    # Full Access (All 3 Sports)
    'full_access': {
        1: 250.0,   # 1 month
        3: 600.0,   # 3 months
        6: 1000.0   # 6 months
    }
}

# Currency
CURRENCY = 'EUR'

# Legacy pricing (kept for backward compatibility)
PRICE_TENNIS_MONTHLY = float(os.getenv('PRICE_TENNIS_MONTHLY', '120.0'))
PRICE_BASKETBALL_MONTHLY = float(os.getenv('PRICE_BASKETBALL_MONTHLY', '120.0'))
PRICE_HANDBALL_MONTHLY = float(os.getenv('PRICE_HANDBALL_MONTHLY', '120.0'))
PRICE_BASIC_MONTHLY = float(os.getenv('PRICE_BASIC_MONTHLY', '120.0'))
PRICE_ADVANCED_MONTHLY = float(os.getenv('PRICE_ADVANCED_MONTHLY', '180.0'))
PRICE_PREMIUM_MONTHLY = float(os.getenv('PRICE_PREMIUM_MONTHLY', '250.0')) 