# Satta AI Telegram Bot - Deployment Preparation (Milestone 3)

This document outlines the steps to prepare and deploy the Satta AI Telegram Bot on a production VPS (Linux/Ubuntu) or run it locally on Windows.

## Project Structure

The project follows a clean, modular structure:

```
/satta-ai-bot
├── app/
│   ├── __init__.py
│   ├── config.py           # Environment variable loading, logging setup
│   ├── bot.py              # Telegram bot core logic, error handling, user registration
│   ├── paypal.py           # PayPal SDK integration, Flask routes for payment callbacks
│   ├── database.py         # SQLAlchemy engine, session management, connection pooling
│   ├── models.py           # SQLAlchemy ORM models (User, Payment)
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── start.py        # /start command handler
│   │   └── pay.py          # /pay command handler (initiates PayPal payment)
│   └── utils/              # Utility functions (currently empty, for future use)
├── main.py                 # Main entry point: starts DB, Flask, and Telegram bot threads
├── requirements.txt        # Python dependencies
├── .env.example            # Example environment variables
├── README.md               # This file
├── deploy.sh               # Deployment script for Linux/Ubuntu VPS
└── start.bat               # Local startup script for Windows
```

## Requirements

*   Python 3.8+
*   PostgreSQL Database
*   Telegram Bot Token
*   PayPal API Credentials (Client ID, Client Secret)
*   Node.js and npm (for PM2 on Linux)

## Local Setup (Windows)

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/YOUR_GITHUB_REPO/satta-ai-bot.git
    cd satta-ai-bot
    ```
2.  **Create `.env` file:**
    Copy `.env.example` to `.env` and fill in your credentials.
    ```bash
    copy .env.example .env
    ```
    Edit `.env` with your `TELEGRAM_BOT_TOKEN`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, and `DB_URI` (e.g., `postgresql://user:password@localhost:5432/your_db`).
    Ensure `FLASK_PORT=5000` and `BOT_MODE=polling`.
3.  **Run `start.bat`:**
    Double-click `start.bat` or run it from Command Prompt. This script will:
    *   Create a Python virtual environment (`myenv`).
    *   Install all dependencies from `requirements.txt`.
    *   Start `main.py`, which in turn starts the Flask app and Telegram bot in separate threads.

    ```bash
    start.bat
    ```

## Deployment on Linux/Ubuntu VPS

This section guides you through deploying the bot on a Linux/Ubuntu VPS using `deploy.sh`, PM2 for process management, and Nginx as a reverse proxy.

### 1. Prepare your VPS

*   **Update your system:**
    ```bash
    sudo apt update && sudo apt upgrade -y
    ```
*   **Install Git, Python3, pip, and PostgreSQL client libraries:**
    ```bash
    sudo apt install -y git python3-venv python3-dev libpq-dev nginx curl
    ```
*   **Install Node.js and npm (for PM2):**
    Follow instructions from NodeSource for your Ubuntu version:
    ```bash
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
    sudo apt-get install -y nodejs
    ```
*   **Install PM2 globally:**
    ```bash
    sudo npm install pm2 -g
    ```
    After installation, PM2 will provide a command to set up startup scripts. **Run that command** to ensure PM2 starts automatically on boot. It will look something like:
    ```bash
    sudo env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u <your_username> --hp /home/<your_username>
    ```
    Replace `<your_username>` with your actual username.

### 2. Run the Deployment Script

The `deploy.sh` script automates most of the setup.

1.  **Clone the repository on your VPS:**
    ```bash
    git clone https://github.com/YOUR_GITHUB_REPO/satta-ai-bot.git /opt/satta-ai-bot
    cd /opt/satta-ai-bot
    ```
    *(Adjust `/opt/satta-ai-bot` if you prefer a different directory)*
2.  **Make the script executable:**
    ```bash
    chmod +x deploy.sh
    ```
3.  **Execute the deployment script:**
    ```bash
    ./deploy.sh
    ```
    The script will prompt you at certain stages, especially for `.env` configuration and Alembic review.

### 3. Configure Environment Variables (`.env`)

The `deploy.sh` script will guide you to create and edit your `.env` file.

*   **Create the file:**
    ```bash
    cp .env.example .env
    ```
*   **Edit `.env`:**
    Use `nano .env` or your preferred editor.
    ```ini
    TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
    PAYPAL_CLIENT_ID=YOUR_PAYPAL_CLIENT_ID
    PAYPAL_CLIENT_SECRET=YOUR_PAYPAL_CLIENT_SECRET
    DB_URI=postgresql://user:password@your_db_host:5432/your_db_name
    FLASK_PORT=5000
    BOT_MODE=polling
    ```
    **IMPORTANT:**
    *   Replace `YOUR_TELEGRAM_BOT_TOKEN`, `YOUR_PAYPAL_CLIENT_ID`, `YOUR_PAYPAL_CLIENT_SECRET` with your actual live credentials.
    *   Set `DB_URI` to your PostgreSQL database connection string.
    *   In `app/handlers/pay.py`, remember to replace `"YOUR_PUBLIC_DOMAIN_OR_IP"` with your actual VPS public IP or domain name for PayPal callback URLs.

### 4. Database Migrations (Alembic)

The `deploy.sh` script will handle Alembic initialization and upgrades.

*   **Initial Alembic Setup:** If `alembic.ini` is not found, the script will run `alembic init -t async migrations`.
    *   **Action Required:** You will need to manually edit `migrations/env.py` to import your `Base` metadata.
        Find the line `from app.models import Base` and `target_metadata = Base.metadata`.
        ```python
        # migrations/env.py (excerpt)
        from app.models import Base # Add this line
        target_metadata = Base.metadata # Ensure this line is present and points to Base.metadata
        ```
*   **Applying Migrations:** The script will then run `alembic upgrade head` to apply any pending migrations.

### 5. Running the Bot in the Background (PM2)

The `deploy.sh` script configures and starts your application using PM2.

*   **PM2 Configuration (`ecosystem.config.js`):**
    The script creates `ecosystem.config.js` in your project root, defining how PM2 should run your `main.py`.
*   **Starting with PM2:**
    ```bash
    pm2 start ecosystem.config.js
    pm2 save
    ```
    This starts your bot and saves the process list, so PM2 will automatically restart it on server reboots.
*   **Checking Status:**
    ```bash
    pm2 list
    pm2 logs satta-ai-bot
    ```

### 6. systemd Service for PM2 Startup

The `deploy.sh` script also creates a `systemd` service file (`/etc/systemd/system/satta-ai-bot.service`) to ensure PM2 itself starts on boot and resurrects your application processes.

*   **Reload systemd and enable service:**
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl enable satta-ai-bot
    ```
*   **Check service status:**
    ```bash
    sudo systemctl status satta-ai-bot
    ```

### 7. Nginx Reverse Proxy (for Flask)

The `deploy.sh` script sets up Nginx to proxy requests from port 80 to your Flask application running on `FLASK_PORT` (default 5000).

*   **Action Required:** Edit the Nginx configuration file `/etc/nginx/sites-available/satta-ai-bot` and replace `YOUR_PUBLIC_DOMAIN_OR_IP` with your actual domain or VPS IP address.
*   **Restart Nginx:**
    ```bash
    sudo systemctl restart nginx
    ```

## Important Notes

*   **Security:** Ensure your `.env` file is not publicly accessible. PM2 and systemd handle environment variables securely.
*   **Firewall:** Configure your VPS firewall (e.g., `ufw`) to allow incoming traffic on ports 80 (for Nginx/Flask) and any other ports your bot might need.
*   **Domain/IP:** Always replace placeholder `YOUR_PUBLIC_DOMAIN_OR_IP` with your actual public domain or IP address in `app/handlers/pay.py` and Nginx configuration.
*   **Error Handling:** The code includes basic logging and exception handling. Monitor your application logs (`pm2 logs satta-ai-bot`) for any issues.
*   **Alembic:** For schema changes, always use Alembic to generate and apply migrations:
    ```bash
    # Activate virtual environment
    source /opt/satta-ai-bot/venv/bin/activate
    # Generate a new migration script
    alembic revision --autogenerate -m "Description of changes"
    # Review the generated script, then apply
    alembic upgrade head
    # Deactivate virtual environment
    deactivate
