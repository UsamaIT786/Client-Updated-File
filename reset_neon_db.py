#!/usr/bin/env python3
"""
Neon DB Reset and Initialization Script
This script will reset and initialize your Neon PostgreSQL database
"""

import os
import sys
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import SQLAlchemyError, OperationalError
import env_config
from database import Base, SessionLocal

def test_neon_connection():
    """Test connection to Neon DB"""
    try:
        print("🔗 Testing Neon DB connection...")
        print(f"📍 Database URL: {env_config.DATABASE_URL}")
        
        # Create engine with specific PostgreSQL settings for Neon
        engine = create_engine(
            env_config.DATABASE_URL,
            echo=False,  # Set to True for debugging SQL queries
            pool_pre_ping=True,  # Verify connections before use
            pool_recycle=300,    # Recycle connections every 5 minutes
            connect_args={
                "sslmode": "require",  # Neon requires SSL
                "connect_timeout": 10
            }
        )
        
        # Test basic connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            version = result.fetchone()[0]
            print(f"✅ Connected to Neon PostgreSQL!")
            print(f"📊 Server version: {version}")
            
            # Check current database name
            result = conn.execute(text("SELECT current_database();"))
            db_name = result.fetchone()[0]
            print(f"🗄️  Current database: {db_name}")
            
            return engine
            
    except OperationalError as e:
        print(f"❌ Connection failed: {str(e)}")
        print("\n🔧 Troubleshooting for Neon DB:")
        print("1. Verify your Neon connection string format:")
        print("   postgresql://[username]:[password]@[endpoint]/[database]?sslmode=require")
        print("2. Check if your Neon project is active (not sleeping)")
        print("3. Verify username/password are correct")
        print("4. Make sure the database exists in your Neon project")
        return None
        
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        return None

def check_existing_tables(engine):
    """Check what tables currently exist"""
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if tables:
            print(f"📋 Existing tables: {', '.join(tables)}")
            return tables
        else:
            print("📋 No tables found in database")
            return []
            
    except Exception as e:
        print(f"⚠️  Could not check existing tables: {str(e)}")
        return []

def reset_neon_database():
    """Reset and initialize Neon database"""
    
    print("🚀 Neon DB Reset and Initialization")
    print("=" * 50)
    
    # Test connection first
    engine = test_neon_connection()
    if not engine:
        return False
    
    try:
        # Check existing tables
        existing_tables = check_existing_tables(engine)
        
        if existing_tables:
            print(f"\n🗑️  Dropping {len(existing_tables)} existing tables...")
            Base.metadata.drop_all(bind=engine)
            print("✅ All existing tables dropped")
        
        # Create all tables fresh
        print("🏗️  Creating fresh tables...")
        Base.metadata.create_all(bind=engine)
        print("✅ All tables created successfully")
        
        # Verify table creation
        print("\n🔍 Verifying table creation...")
        new_tables = check_existing_tables(engine)
        
        expected_tables = ['users', 'subscriptions', 'payments', 'matches', 'notification_logs']
        missing_tables = set(expected_tables) - set(new_tables)
        
        if missing_tables:
            print(f"⚠️  Warning: Missing tables: {', '.join(missing_tables)}")
        else:
            print("✅ All expected tables created successfully")
        
        # Test database operations
        print("\n🧪 Testing database operations...")
        with engine.connect() as conn:
            # Test a simple query
            conn.execute(text("SELECT 1;"))
            
            # Test table access
            for table in expected_tables:
                conn.execute(text(f"SELECT COUNT(*) FROM {table};"))
            
        print("✅ Database operations test passed")
        
        # Test SQLAlchemy session
        print("🧪 Testing SQLAlchemy session...")
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1;"))
            print("✅ SQLAlchemy session test passed")
        finally:
            db.close()
        
        print("\n🎉 Neon Database reset completed successfully!")
        print("🚀 Your bot is ready to use with Neon DB!")
        
        # Show connection details
        print(f"\n📊 Database Details:")
        print(f"   • Database Type: PostgreSQL (Neon)")
        print(f"   • Tables Created: {len(new_tables)}")
        print(f"   • Connection: Active")
        
        return True
        
    except SQLAlchemyError as e:
        print(f"❌ Database error: {str(e)}")
        print("\n🔧 Common Neon DB issues:")
        print("1. Database might be sleeping - visit Neon dashboard to wake it")
        print("2. Check if connection limits are exceeded")
        print("3. Verify SSL requirements are met")
        return False
        
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        return False

def show_neon_setup_guide():
    """Show setup guide for Neon DB"""
    print("\n📚 Neon DB Setup Guide:")
    print("=" * 30)
    print("\n1. Get your Neon connection string:")
    print("   • Go to https://console.neon.tech/")
    print("   • Select your project")
    print("   • Go to 'Connection Details'")
    print("   • Copy the connection string")
    
    print("\n2. Add to your .env file:")
    print("   BOT_DATABASE_URL=postgresql://username:password@host/database?sslmode=require")
    
    print("\n3. Connection string format:")
    print("   postgresql://[user]:[password]@[host]/[database]?sslmode=require")
    
    print("\n4. Common issues:")
    print("   • Make sure sslmode=require is included")
    print("   • Database name must exist in your Neon project")
    print("   • Project must be active (not sleeping)")

if __name__ == "__main__":
    
    # Check if BOT_DATABASE_URL is set
    if not env_config.DATABASE_URL or env_config.DATABASE_URL == 'sqlite:///betting_bot.db':
        print("❌ Neon DB URL not configured!")
        print("\nCurrent DATABASE_URL:", env_config.DATABASE_URL)
        show_neon_setup_guide()
        sys.exit(1)
    
    # Check if it's a PostgreSQL URL
    if not env_config.DATABASE_URL.startswith('postgresql://'):
        print("❌ URL doesn't appear to be PostgreSQL!")
        print(f"Current URL: {env_config.DATABASE_URL}")
        print("\nExpected format: postgresql://username:password@host/database?sslmode=require")
        sys.exit(1)
    
    print("⚠️  WARNING: This will delete ALL existing data in your Neon database!")
    confirm = input("Are you sure you want to reset the Neon database? (yes/no): ").lower().strip()
    
    if confirm in ['yes', 'y']:
        success = reset_neon_database()
        sys.exit(0 if success else 1)
    else:
        print("❌ Database reset cancelled")
        sys.exit(0) 