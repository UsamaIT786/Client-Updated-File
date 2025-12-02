module.exports = {
  apps: [
    {
      name: 'betting-bot-simple',
      script: '/home/parthiv/STUDY/bot/myenv/bin/python',
      args: '/home/parthiv/STUDY/bot/run_bot.py --mode simple',
      cwd: '/home/parthiv/STUDY/bot',
      interpreter: 'none',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        NODE_ENV: 'production',
        PYTHONPATH: '/home/parthiv/STUDY/bot',
        PYTHONUNBUFFERED: '1'
      },
      error_file: '/home/parthiv/STUDY/bot/logs/betting-bot-error.log',
      out_file: '/home/parthiv/STUDY/bot/logs/betting-bot-out.log',
      log_file: '/home/parthiv/STUDY/bot/logs/betting-bot-combined.log',
      time: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      restart_delay: 4000,
      max_restarts: 10,
      min_uptime: '10s'
    }
  ]
}; 