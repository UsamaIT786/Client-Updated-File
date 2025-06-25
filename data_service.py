#!/usr/bin/env python3
"""
Separate Data Service for Odds Tracking
This service runs independently from the main bot to ensure
bot commands remain responsive while data is being fetched.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from odds_tracker import odds_tracker

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class DataService:
    def __init__(self):
        self.running = True
        self.tracker = odds_tracker
        
    async def start(self):
        """Start the data service"""
        logger.info("🚀 Starting Data Service...")
        logger.info("📊 This service handles odds tracking independently from the bot")
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            # Run the continuous tracking
            await self.tracker.run_continuous_tracking()
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        except Exception as e:
            logger.error(f"Data service error: {str(e)}")
        finally:
            await self.shutdown()
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
    
    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("🛑 Shutting down Data Service...")
        self.running = False
        
        # Give some time for any ongoing operations to complete
        await asyncio.sleep(2)
        logger.info("✅ Data Service stopped")

async def main():
    """Main function to run the data service"""
    service = DataService()
    await service.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Data service interrupted by user")
    except Exception as e:
        logger.error(f"Failed to start data service: {str(e)}")
        sys.exit(1) 