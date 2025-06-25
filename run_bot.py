#!/usr/bin/env python3
"""
Main startup script for the Betting Analytics Bot
Supports both simple and full production modes
"""

import os
import sys
import subprocess
import threading
import time
import requests
import json
import logging
import argparse
import signal
from database import init_db

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global variables to track processes
data_process = None
bot_process = None
flask_process = None
ngrok_process = None
shutdown_flag = False

def signal_handler(signum, frame):
    """Handle Ctrl+C and other termination signals"""
    global shutdown_flag
    logger.info("🛑 Shutdown signal received...")
    shutdown_flag = True
    
    # Terminate all processes
    processes = [
        ("Data Service", data_process),
        ("Telegram Bot", bot_process), 
        ("Flask Server", flask_process),
        ("Ngrok", ngrok_process)
    ]
    
    for name, process in processes:
        if process and process.poll() is None:  # Process is still running
            logger.info(f"Stopping {name}...")
            try:
                process.terminate()
                process.wait(timeout=5)  # Wait up to 5 seconds
                logger.info(f"✅ {name} stopped")
            except subprocess.TimeoutExpired:
                logger.warning(f"Force killing {name}...")
                process.kill()
            except Exception as e:
                logger.error(f"Error stopping {name}: {e}")
    
    logger.info("✅ All services stopped")
    sys.exit(0)

def start_ngrok():
    """Start ngrok tunnel and get the public URL"""
    global ngrok_process
    logger.info("Starting ngrok tunnel...")
    
    # Start ngrok process for webhook server
    ngrok_process = subprocess.Popen(
        ['ngrok', 'http', '5000'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Give ngrok time to start
    time.sleep(3)
    
    # Get ngrok URL from API
    try:
        response = requests.get('http://localhost:4040/api/tunnels')
        tunnels = response.json()['tunnels']
        
        for tunnel in tunnels:
            if tunnel['proto'] == 'https':
                webhook_url = tunnel['public_url']
                logger.info(f"Ngrok URL: {webhook_url}")
                
                # Update environment variable
                os.environ['NGROK_URL'] = webhook_url
                
                # Update env_config dynamically
                import env_config
                env_config.NGROK_URL = webhook_url
                
                return webhook_url, ngrok_process
                
    except Exception as e:
        logger.error(f"Failed to get ngrok URL: {str(e)}")
        return None, ngrok_process
    
    return None, ngrok_process

def run_flask_server():
    """Run the Flask webhook server"""
    global flask_process
    logger.info("Starting Flask webhook server on port 5000...")
    flask_process = subprocess.Popen([sys.executable, 'webhook_server.py'])
    flask_process.wait()

def run_data_service():
    """Run the separate data service for odds tracking"""
    global data_process
    logger.info("Starting Data Service for odds tracking...")
    data_process = subprocess.Popen([sys.executable, 'data_service.py'])
    data_process.wait()

def run_telegram_bot():
    """Run the Telegram bot"""
    global bot_process
    logger.info("Starting Telegram bot...")
    bot_process = subprocess.Popen([sys.executable, 'telegram_bot.py'])
    bot_process.wait()

def simple_mode():
    """Simple mode - just bot and data service"""
    global shutdown_flag
    
    print("""
    ╔════════════════════════════════════════════╗
    ║      Fast Betting Analytics Bot            ║
    ║        (Simple Mode)                       ║
    ║                                            ║
    ║        Press Ctrl+C to stop                ║
    ╚════════════════════════════════════════════╝
    """)
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize database
    logger.info("🗄️  Initializing database...")
    init_db()
    logger.info("✅ Database ready")
    
    # Start data service in background thread
    logger.info("📊 Starting data service in background...")
    data_thread = threading.Thread(target=run_data_service, daemon=True)
    data_thread.start()
    time.sleep(2)
    logger.info("✅ Data service running separately")
    
    # Start bot (main thread)
    logger.info("🤖 Starting optimized Telegram bot...")
    logger.info("💡 Commands should now respond instantly!")
    logger.info("🛑 Press Ctrl+C to stop all services")
    
    try:
        run_telegram_bot()
    except KeyboardInterrupt:
        logger.info("🛑 Ctrl+C pressed - shutting down...")
        signal_handler(signal.SIGINT, None)
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        signal_handler(signal.SIGTERM, None)

def full_mode():
    """Full production mode with ngrok and webhooks"""
    global shutdown_flag
    
    print("""
    ╔════════════════════════════════════════════╗
    ║      Premium Betting Analytics Bot         ║
    ║         (Full Production Mode)             ║
    ║                                            ║
    ║        Press Ctrl+C to stop                ║
    ╚════════════════════════════════════════════╝
    """)
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize database
    logger.info("Initializing database...")
    init_db()
    logger.info("✅ Database initialized successfully")
    
    # Start ngrok
    logger.info("🌐 Setting up ngrok tunnel...")
    ngrok_url, ngrok_proc = start_ngrok()
    
    if not ngrok_url:
        logger.error("❌ Failed to start ngrok. Exiting...")
        sys.exit(1)
    
    logger.info("✅ Ngrok tunnel established")
    
    # Start Flask webhook server in background
    logger.info("🌐 Starting webhook server...")
    flask_thread = threading.Thread(target=run_flask_server, daemon=True)
    flask_thread.start()
    time.sleep(3)  # Give Flask time to start
    logger.info("✅ Webhook server running")
    
    # Start data service in background
    logger.info("📊 Starting data service...")
    data_thread = threading.Thread(target=run_data_service, daemon=True)
    data_thread.start()
    time.sleep(2)  # Give data service time to start
    logger.info("✅ Data service running")
    
    # Start Telegram bot (main thread)
    logger.info("🤖 Starting Telegram bot...")
    logger.info("🛑 Press Ctrl+C to stop all services")
    
    try:
        run_telegram_bot()
    except KeyboardInterrupt:
        logger.info("🛑 Ctrl+C pressed - shutting down...")
        signal_handler(signal.SIGINT, None)
    except Exception as e:
        logger.error(f"❌ Error running bot: {str(e)}")
        signal_handler(signal.SIGTERM, None)

def main():
    """Main function with mode selection"""
    parser = argparse.ArgumentParser(description='Betting Analytics Bot')
    parser.add_argument('--mode', choices=['simple', 'full'], default='full',
                        help='Run mode: simple (bot only) or full (with ngrok/webhooks)')
    
    args = parser.parse_args()
    
    if args.mode == 'simple':
        simple_mode()
    else:
        full_mode()

if __name__ == "__main__":
    main() 