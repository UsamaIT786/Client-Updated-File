# run_bot.py with PM2 - Management Guide

## ✅ Current Setup
Your `run_bot.py` is now running with PM2 in **Simple Mode**, which includes:
- 🤖 Telegram Bot (handles user commands)
- 📊 Data Service (tracks odds and matches)
- 🔄 Automatic restarts if crashes occur
- 📝 Comprehensive logging

## 📊 Monitoring Commands

```bash
# Check if bot is running
pm2 status

# View live logs (Ctrl+C to exit)
pm2 logs betting-bot-simple

# View last 20 lines of logs
pm2 logs betting-bot-simple --lines 20

# Monitor real-time CPU/Memory usage
pm2 monit
```

## 🎛️ Control Commands

```bash
# Restart the bot
pm2 restart betting-bot-simple

# Stop the bot
pm2 stop betting-bot-simple

# Start the bot (if stopped)
pm2 start betting-bot-simple

# View detailed info about the process
pm2 describe betting-bot-simple
```

## 🗂️ Log Files Location
- **All Logs**: `/home/parthiv/STUDY/bot/logs/betting-bot-*.log`
- **Output Logs**: `betting-bot-out.log` (normal operation)
- **Error Logs**: `betting-bot-error.log` (errors and warnings)
- **Combined Logs**: `betting-bot-combined.log` (everything)

## 🌙 Overnight Testing Setup

Your bot will run all night and:
- ✅ **Keep running continuously** (even if you close terminal)
- ✅ **Auto-restart** if it crashes (up to 10 times)
- ✅ **Restart after system reboot** automatically
- ✅ **Log all activity** for morning review
- ✅ **Monitor memory usage** (restarts if > 1GB)

## 📋 Morning Checklist

After overnight testing, check:

```bash
# 1. Is it still running?
pm2 status

# 2. How many times did it restart? (↺ column)
pm2 list

# 3. Check what happened overnight
pm2 logs betting-bot-simple --lines 100

# 4. Check for any errors
pm2 logs betting-bot-simple --err --lines 50
```

## 🔧 Mode Switching (if needed)

### Switch to Full Mode (with webhooks + ngrok):
```bash
pm2 stop betting-bot-simple
# Edit ecosystem.config.js: change '--mode simple' to '--mode full'
pm2 reload ecosystem.config.js
```

### Switch back to Simple Mode:
```bash
pm2 stop betting-bot-simple
# Edit ecosystem.config.js: change '--mode full' to '--mode simple'  
pm2 reload ecosystem.config.js
```

## 🚨 Emergency Commands

```bash
# If bot becomes unresponsive
pm2 restart betting-bot-simple

# If you need to completely reset
pm2 delete betting-bot-simple
pm2 start ecosystem.config.js

# To stop everything
pm2 stop all

# To see real-time activity
pm2 logs betting-bot-simple
```

## 🎯 What's Running in Simple Mode

Your `run_bot.py --mode simple` starts:
1. **Database initialization**
2. **Data Service** (in background thread) - tracks odds
3. **Telegram Bot** (main thread) - handles user commands
4. **Automatic crash recovery**
5. **Graceful shutdown handling**

## ✨ Benefits of This Setup

- **Single process** = easier to manage
- **PM2 management** = automatic restarts & monitoring  
- **Combined logging** = all activity in one place
- **Production ready** = can run for days/weeks
- **Memory efficient** = both services in one process

Your bot is now ready for overnight testing! 🌙 