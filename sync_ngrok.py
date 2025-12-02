#!/usr/bin/env python3
"""
Utility script to sync ngrok URL with environment file
This can be used to manually update the .env file with the current ngrok URL
"""

import requests
import sys
import os
from datetime import datetime

def get_current_ngrok_url():
    """Get the current ngrok URL from the local API"""
    try:
        response = requests.get('http://localhost:4040/api/tunnels')
        tunnels = response.json()['tunnels']
        
        for tunnel in tunnels:
            if tunnel['proto'] == 'https':
                return tunnel['public_url']
        
        print("❌ No HTTPS tunnel found")
        return None
        
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to ngrok API. Is ngrok running?")
        print("💡 Start ngrok with: ngrok http 5000")
        return None
    except Exception as e:
        print(f"❌ Error getting ngrok URL: {str(e)}")
        return None

def update_env_file(key, value):
    """Update a specific environment variable in the .env file"""
    env_file_path = '.env'
    
    # Read existing .env file
    lines = []
    key_found = False
    
    try:
        with open(env_file_path, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"❌ .env file not found at {env_file_path}")
        return False
    
    # Update the key
    updated_lines = []
    for line in lines:
        if line.strip().startswith(f'{key}='):
            updated_lines.append(f'{key}={value}\n')
            key_found = True
        else:
            updated_lines.append(line)
    
    # If key wasn't found, add it
    if not key_found:
        updated_lines.append(f'{key}={value}\n')
    
    # Write back to file
    try:
        with open(env_file_path, 'w') as f:
            f.writelines(updated_lines)
        return True
    except Exception as e:
        print(f"❌ Failed to update .env file: {str(e)}")
        return False

def show_current_env_url():
    """Show the current NGROK_URL from .env file"""
    try:
        with open('.env', 'r') as f:
            for line in f:
                if line.strip().startswith('NGROK_URL='):
                    current_url = line.strip().split('=', 1)[1]
                    print(f"📋 Current .env NGROK_URL: {current_url}")
                    return current_url
        print("❌ NGROK_URL not found in .env file")
        return None
    except FileNotFoundError:
        print("❌ .env file not found")
        return None

def main():
    """Main function"""
    print("🌐 Ngrok URL Sync Utility")
    print("=" * 40)
    
    # Show current env URL
    current_env_url = show_current_env_url()
    
    # Get current ngrok URL
    print("\n🔍 Checking ngrok status...")
    ngrok_url = get_current_ngrok_url()
    
    if not ngrok_url:
        sys.exit(1)
    
    print(f"🌍 Current ngrok URL: {ngrok_url}")
    
    # Check if they match
    if current_env_url and current_env_url == ngrok_url:
        print("✅ URLs are already in sync!")
        sys.exit(0)
    
    # Update .env file
    print(f"\n🔄 Updating .env file...")
    if update_env_file('NGROK_URL', ngrok_url):
        print(f"✅ Successfully updated NGROK_URL in .env file")
        print(f"📝 New URL: {ngrok_url}")
        print(f"⏰ Updated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Try to reload env_config if it's available
        try:
            import env_config
            env_config.reload_env()
            print("🔄 Reloaded environment configuration")
        except ImportError:
            print("ℹ️ env_config not available for reload")
        except Exception as e:
            print(f"⚠️ Could not reload env_config: {str(e)}")
    else:
        print("❌ Failed to update .env file")
        sys.exit(1)

if __name__ == "__main__":
    main() 