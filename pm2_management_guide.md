# PM2 Bot Management Guide

## Status & Monitoring Commands

```bash
# Check status of all processes
pm2 status

# Monitor in real-time (press Ctrl+C to exit)
pm2 monit

# View logs (live streaming)
pm2 logs

# View logs for specific service
pm2 logs telegram-bot
pm2 logs data-service

# View last 100 lines of logs
pm2 logs --lines 100

# Clear logs
pm2 flush
```

## Control Commands

```bash
# Restart specific service
pm2 restart telegram-bot
pm2 restart data-service

# Restart all services
pm2 restart all

# Stop specific service
pm2 stop telegram-bot
pm2 stop data-service

# Stop all services
pm2 stop all

# Start stopped service
pm2 start telegram-bot
pm2 start data-service

# Delete a service (removes from PM2)
pm2 delete telegram-bot
pm2 delete data-service

# Reload ecosystem config (after changes)
pm2 reload ecosystem.config.js
```

## Log Files Location

Your logs are saved to:
- **Telegram Bot Logs**: `/home/parthiv/STUDY/bot/logs/telegram-bot-*.log`
- **Data Service Logs**: `/home/parthiv/STUDY/bot/logs/data-service-*.log`

## Health Monitoring

```bash
# Quick health check
pm2 ping

# Detailed info about a process
pm2 describe telegram-bot

# Show process list with detailed info
pm2 list

# Memory and CPU usage
pm2 show telegram-bot
```

## Automatic Restart Configuration

Your bot will automatically:
- ✅ Restart if it crashes
- ✅ Restart after system reboot
- ✅ Restart if memory usage exceeds 1GB
- ✅ Stop trying to restart after 10 failed attempts
- ✅ Wait 4 seconds between restart attempts

## Startup Configuration

- PM2 will automatically start your bot on system boot
- Your process list is saved and will be restored after reboot
- Services will start in the correct order with proper delays

## Testing Overnight

The bot is now ready for overnight testing. It will:
1. Keep running continuously
2. Automatically restart if any issues occur
3. Maintain logs for debugging
4. Resume automatically after system restarts

## Emergency Commands

```bash
# If bot becomes unresponsive
pm2 restart all

# If you need to completely reset
pm2 delete all
pm2 start ecosystem.config.js

# To stop everything
pm2 stop all

# To disable auto-startup
pm2 unstartup
```

## Important Notes

- The bot uses your virtual environment (`myenv`) automatically
- All environment variables are preserved
- Logs rotate automatically to prevent disk space issues
- PM2 daemon runs independently of your terminal session 