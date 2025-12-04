import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
from app.config import Config, logger

# SQLAlchemy Base
Base = declarative_base()

class DatabaseManager:
    """
    Manages the database connection, session, and engine.
    Ensures production-safe connection pooling.
    """
    def __init__(self):
        self.engine = None
        self.Session = None

    def connect(self):
        """
        Establishes a database connection using the URI from Config.
        Configures a production-safe connection pool.
        """
        try:
            # Use a connection pool for production
            self.engine = create_engine(
                Config.DB_URI,
                pool_size=10,       # Maintain 10 connections in the pool
                max_overflow=20,    # Allow up to 20 overflow connections
                pool_timeout=30,    # Wait 30 seconds for a connection
                pool_recycle=1800,  # Recycle connections after 30 minutes
                echo=False          # Set to True for SQL logging (debug only)
            )
            self.Session = sessionmaker(bind=self.engine)
            logger.info("Database connected successfully with connection pooling.")
        except SQLAlchemyError as e:
            logger.critical(f"Database connection failed: {e}")
            raise

    def get_session(self):
        """
        Returns a new database session.
        """
        if not self.Session:
            logger.error("Database session not initialized. Call connect() first.")
            raise RuntimeError("Database session not initialized.")
        return self.Session()

    def create_all_tables(self):
        """
        Creates all tables defined in models.py if they don't exist.
        This is typically used for initial setup or testing, Alembic is preferred for migrations.
        """
        if not self.engine:
            logger.error("Database engine not initialized. Call connect() first.")
            raise RuntimeError("Database engine not initialized.")
        try:
            Base.metadata.create_all(self.engine)
            logger.info("All database tables created (if not already existing).")
        except SQLAlchemyError as e:
            logger.error(f"Error creating tables: {e}")
            raise

# Initialize the database manager
db_manager = DatabaseManager()
