# Premium Betting Analytics Bot 🎯

A sophisticated Telegram bot that provides real-time betting analytics by monitoring when favorites are trailing at halftime across Tennis, Basketball, and Handball matches.

## Features

### 🔔 Notification System
- **Tennis**: Alerts when favorite loses the first set
- **Basketball**: Alerts when favorite trails at halftime  
- **Handball**: Alerts when favorite trails at halftime
- Real-time odds tracking using Bet365 API
- Automatic favorite detection based on pre-match odds

### 💳 Subscription Plans
- **Single Sport Plans** ($29.99/month)
  - Tennis only
  - Basketball only
  - Handball only
- **Bundle Plans**
  - Basic: Choose 1 sport ($29.99/month)
  - Advanced: Choose 2 sports ($49.99/month)
  - Premium: All 3 sports ($79.99/month)
  - Custom: Build your own plan

### 📱 Dual Channel System
- **Free Channel**: Match start notifications
- **Premium Channel**: Halftime trailing alerts with live odds

## Prerequisites

- Python 3.8+
- Telegram Bot Token
- PayPal Sandbox Account
- Bet365 API Token
- ngrok installed

## Setup Instructions

### 1. Clone the Repository
```bash
git clone <repository-url>
cd bot
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create a `.env` file in the project root:

```env
# Bet365 API Configuration
API_TOKEN=your_bet365_api_token

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
PREMIUM_CHANNEL_ID=@your_premium_channel
FREE_CHANNEL_ID=@your_free_channel

# PayPal Sandbox Configuration
PAYPAL_CLIENT_ID=your_paypal_sandbox_client_id
PAYPAL_CLIENT_SECRET=your_paypal_sandbox_client_secret
PAYPAL_MODE=sandbox

# Database Configuration
DATABASE_URL=sqlite:///betting_bot.db

# Admin Configuration
ADMIN_TELEGRAM_ID=your_telegram_user_id

# Subscription Pricing (USD)
PRICE_TENNIS_MONTHLY=29.99
PRICE_BASKETBALL_MONTHLY=29.99
PRICE_HANDBALL_MONTHLY=29.99
PRICE_BASIC_MONTHLY=29.99
PRICE_ADVANCED_MONTHLY=49.99
PRICE_PREMIUM_MONTHLY=79.99
```

### 4. Create Telegram Bot
1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Create a new bot with `/newbot`
3. Copy the bot token to your `.env` file

### 5. Create Telegram Channels
1. Create two channels on Telegram:
   - Premium channel (private)
   - Free channel (public)
2. Add your bot as admin to both channels
3. Get channel IDs and add to `.env` file

### 6. Setup PayPal Sandbox
1. Go to [PayPal Developer](https://developer.paypal.com/)
2. Create a sandbox account
3. Get Client ID and Secret
4. Add credentials to `.env` file

### 7. Install ngrok
```bash
# Download from https://ngrok.com/download
# Or use package manager:
# macOS
brew install ngrok

# Ubuntu
snap install ngrok
```

## Running the Bot

### Option 1: Using the startup script (Recommended)
```bash
python run_bot.py
```

This will:
- Start ngrok tunnel
- Launch Flask webhook server
- Start the Telegram bot
- Initialize the database

### Option 2: Run components separately
```bash
# Terminal 1: Start ngrok
ngrok http 5000

# Terminal 2: Run webhook server
python webhook_server.py

# Terminal 3: Run the bot
python telegram_bot.py
```

## Project Structure

```
bot/
├── telegram_bot.py      # Main Telegram bot logic
├── database.py          # Database models (SQLAlchemy)
├── odds_tracker.py      # Live odds monitoring service
├── paypal_integration.py # PayPal payment handling
├── webhook_server.py    # Flask server for PayPal callbacks
├── winplay.py          # Bet365 API integration
├── env_config.py       # Environment configuration
├── run_bot.py          # Startup script
├── requirements.txt    # Python dependencies
└── README.md          # This file
```

## How It Works

1. **Match Monitoring**
   - The bot continuously fetches upcoming matches
   - Stores pre-match odds and identifies favorites
   - Monitors live matches every 30 seconds

2. **Notification Logic**
   - Free channel: Notified when matches are starting
   - Premium channel: Notified when favorite is trailing at halftime
   - Includes pre-match odds, current score, and live odds

3. **Subscription Management**
   - Users interact with the bot to select plans
   - PayPal integration for secure payments
   - Automatic subscription activation upon payment

## Testing

### Test PayPal Integration
1. Use PayPal sandbox accounts
2. Complete a test payment
3. Verify subscription activation

### Test Notifications
1. Monitor the channels for notifications
2. Check database for match records
3. Review notification logs

## Maintenance

### Database Backup
```bash
# Backup SQLite database
cp betting_bot.db betting_bot_backup_$(date +%Y%m%d).db
```

### Monitor Logs
```bash
# View bot logs
tail -f bot.log
```

### Update Odds
The bot automatically updates odds every 30 seconds when running.

## Troubleshooting

### Bot Not Responding
- Check bot token is correct
- Ensure bot is added to channels as admin
- Verify internet connection

### Payment Issues
- Confirm PayPal credentials are correct
- Check ngrok is running and URL is accessible
- Verify webhook server is running

### No Notifications
- Check Bet365 API token is valid
- Ensure matches are actually in progress
- Verify database is initialized

## Support

For issues or questions:
1. Check the logs for error messages
2. Ensure all environment variables are set
3. Verify all services are running

## License

This project is for educational purposes. Ensure compliance with local gambling regulations. 