#!/usr/bin/env python3
"""
Setup Checker for Premium Betting Analytics Bot
This script checks if all required environment variables are properly configured.
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def check_env_var(var_name, description, placeholder_values=None):
    """Check if an environment variable is set and valid"""
    value = os.getenv(var_name)
    placeholder_values = placeholder_values or []
    
    if not value:
        print(f"❌ {var_name}: Not set")
        print(f"   Description: {description}")
        return False
    elif value in placeholder_values:
        print(f"⚠️  {var_name}: Still using placeholder value")
        print(f"   Current: {value}")
        print(f"   Description: {description}")
        return False
    else:
        print(f"✅ {var_name}: Configured")
        return True

def main():
    print("🔍 Premium Betting Analytics Bot - Setup Checker")
    print("=" * 60)
    
    all_good = True
    
    # Check Telegram Bot Configuration
    print("\n📱 Telegram Bot Configuration:")
    all_good &= check_env_var(
        'TELEGRAM_BOT_TOKEN', 
        'Get this from @BotFather on Telegram',
        ['YOUR_TELEGRAM_BOT_TOKEN']
    )
    
    # Make channel IDs optional
    print("\n📱 Channel Configuration (Optional - for broadcast channels):")
    premium_channel = os.getenv('PREMIUM_CHANNEL_ID')
    free_channel = os.getenv('FREE_CHANNEL_ID')
    
    if premium_channel and premium_channel not in ['@your_premium_channel', '@placeholder_premium']:
        print(f"✅ PREMIUM_CHANNEL_ID: {premium_channel}")
    else:
        print(f"ℹ️  PREMIUM_CHANNEL_ID: Not configured (notifications will go directly to subscribers)")
    
    if free_channel and free_channel not in ['@your_free_channel', '@placeholder_free']:
        print(f"✅ FREE_CHANNEL_ID: {free_channel}")
    else:
        print(f"ℹ️  FREE_CHANNEL_ID: Not configured (notifications will go directly to subscribers)")
    
    # Check PayPal Configuration
    print("\n💳 PayPal Configuration:")
    all_good &= check_env_var(
        'PAYPAL_CLIENT_ID', 
        'PayPal Sandbox Client ID from developer.paypal.com',
        ['YOUR_PAYPAL_SANDBOX_CLIENT_ID']
    )
    all_good &= check_env_var(
        'PAYPAL_CLIENT_SECRET', 
        'PayPal Sandbox Client Secret from developer.paypal.com',
        ['YOUR_PAYPAL_SANDBOX_CLIENT_SECRET']
    )
    
    # Check API Configuration
    print("\n🔗 API Configuration:")
    api_token = os.getenv('API_TOKEN')
    if api_token and api_token != 'YOUR_API_TOKEN':
        print(f"✅ API_TOKEN: Configured")
    else:
        print(f"⚠️  API_TOKEN: Using default token")
        print("   You may want to use your own Bet365 API token")
    
    # Check Admin Configuration
    print("\n👤 Admin Configuration:")
    all_good &= check_env_var(
        'ADMIN_TELEGRAM_ID', 
        'Your Telegram user ID (get from @userinfobot)',
        ['YOUR_ADMIN_TELEGRAM_ID']
    )
    
    # Check Database
    print("\n🗄️  Database Configuration:")
    db_url = os.getenv('BOT_DATABASE_URL', 'sqlite:///betting_bot.db')
    print(f"✅ BOT_DATABASE_URL: {db_url}")
    
    print("\n" + "=" * 60)
    
    if all_good:
        print("🎉 All required configurations are set! You can run the bot.")
        print("\n💡 Notification System:")
        print("   • Notifications will be sent directly to subscribers")
        print("   • No channels required - users get personal messages")
        print("\nTo start the bot, run:")
        print("   python run_bot.py")
    else:
        print("❌ Some configurations are missing or using placeholder values.")
        print("\n📋 Setup Instructions:")
        print("\n1. Create a .env file in the project root with:")
        print("""
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_actual_bot_token_from_botfather

# PayPal Sandbox Configuration  
PAYPAL_CLIENT_ID=your_paypal_client_id
PAYPAL_CLIENT_SECRET=your_paypal_client_secret
PAYPAL_MODE=sandbox

# Admin Configuration
ADMIN_TELEGRAM_ID=your_telegram_user_id

# API Configuration (optional - using default)
API_TOKEN=215845-ME7THuixJ1hOxE

# Database (no changes needed)
BOT_DATABASE_URL=sqlite:///betting_bot.db

# Optional: Channels (leave out if sending direct messages only)
# PREMIUM_CHANNEL_ID=@your_premium_channel
# FREE_CHANNEL_ID=@your_free_channel
""")
        
        print("\n2. How to get these values:")
        print("   • Telegram Bot Token: Message @BotFather on Telegram")
        print("   • PayPal Credentials: Visit developer.paypal.com")
        print("   • Your Telegram ID: Message @userinfobot on Telegram")
        print("   • Channels: Optional - only if you want broadcast channels")
        
        print("\n3. After setting up .env, run this checker again:")
        print("   python setup_checker.py")

if __name__ == "__main__":
    main() 