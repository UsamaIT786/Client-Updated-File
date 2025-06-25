from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Float, JSON, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import env_config

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False)
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    subscriptions = relationship("Subscription", back_populates="user")
    payments = relationship("Payment", back_populates="user")

class Subscription(Base):
    __tablename__ = 'subscriptions'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    plan_type = Column(String(50), nullable=False)  # 'single_sport', 'two_sports', 'full_access'
    sports = Column(JSON, nullable=True)  # List of sports (e.g., ['tennis', 'basketball'])
    start_date = Column(DateTime, default=datetime.utcnow)
    end_date = Column(DateTime, nullable=False)
    duration_months = Column(Integer, default=1)  # Duration of the subscription
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="subscriptions")

class Payment(Base):
    __tablename__ = 'payments'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    paypal_payment_id = Column(String(100), unique=True, nullable=False)
    paypal_payer_id = Column(String)
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default='EUR')  # Changed default to EUR
    status = Column(String(20), default='pending')  # pending, completed, failed
    plan_type = Column(String(50), nullable=False)
    sports = Column(JSON, nullable=True)  # List of sports
    duration_months = Column(Integer, default=1)  # New field for subscription duration
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="payments")

class Match(Base):
    __tablename__ = 'matches'
    
    id = Column(Integer, primary_key=True)
    event_id = Column(String, unique=True)
    sport = Column(String)  # 'tennis', 'basketball', 'handball'
    home_team = Column(String)
    away_team = Column(String)
    league_name = Column(String)
    start_time = Column(DateTime)
    
    # Pre-match odds
    pre_match_home_odds = Column(Float)
    pre_match_away_odds = Column(Float)
    pre_match_draw_odds = Column(Float, nullable=True)  # Not for tennis
    pre_match_favorite = Column(String)  # 'home' or 'away'
    
    # Match status
    status = Column(String)  # 'scheduled', 'live', 'halftime', 'finished'
    current_score_home = Column(Integer, default=0)
    current_score_away = Column(Integer, default=0)
    
    # Live odds tracking
    halftime_home_odds = Column(Float)
    halftime_away_odds = Column(Float)
    halftime_draw_odds = Column(Float, nullable=True)
    
    # Notifications
    start_notification_sent = Column(Boolean, default=False)
    halftime_notification_sent = Column(Boolean, default=False)
    favorite_trailing_at_halftime = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class NotificationLog(Base):
    __tablename__ = 'notification_logs'
    
    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey('matches.id'))
    channel_type = Column(String)  # 'premium' or 'free'
    notification_type = Column(String)  # 'match_start' or 'halftime_trailing'
    content = Column(JSON)
    sent_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=True)
    error_message = Column(String, nullable=True)

# Database setup with Neon-specific configuration
def create_database_engine():
    """Create database engine with Neon-specific settings"""
    if env_config.DATABASE_URL.startswith('postgresql://'):
        # Neon PostgreSQL configuration
        return create_engine(
            env_config.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,  # Verify connections before use
            pool_recycle=300,    # Recycle connections every 5 minutes
            pool_size=5,         # Connection pool size
            max_overflow=10,     # Additional connections if pool is full
            connect_args={
                "sslmode": "require",
                "connect_timeout": 10,
                "application_name": "betting_bot"
            }
        )
    else:
        # SQLite or other databases
        return create_engine(env_config.DATABASE_URL)

# Create engine
engine = create_database_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Initialize the database by creating all tables"""
    try:
        Base.metadata.create_all(bind=engine)
        print("Database tables created successfully")
    except Exception as e:
        print(f"Error creating database tables: {str(e)}")
        raise

def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 