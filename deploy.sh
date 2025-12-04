#!/bin/bash

# This script prepares and deploys the Satta AI Bot on a Linux/Ubuntu VPS.
# It assumes a fresh Ubuntu installation or a clean environment.

# --- Configuration ---
PROJECT_DIR="/opt/satta-ai-bot" # Where the project will be deployed
VENV_DIR="$PROJECT_DIR/venv"
SERVICE_NAME="satta-ai-bot"
FLASK_PORT=5000 # Must match FLASK_PORT in .env

# --- Functions ---
log_info() {
    echo -e "\e[32m[INFO]\e[0m $1"
}

log_warn() {
    echo -e "\e[33m[WARN]\e[0m $1"
}

log_error() {
    echo -e "\e[31m[ERROR]\e[0m $1"
    exit 1
}

check_command() {
    command -v "$1" >/dev/null 2>&1 || { log_error "$1 is not installed. Please install it and try again."; }
}

# --- Pre-deployment Checks ---
log_info "Starting deployment preparation..."
check_command "git"
check_command "python3"
check_command "pip3"
check_command "npm" # For PM2
check_command "pm2" # Check if PM2 is globally installed

# --- 1. Update System and Install Dependencies ---
log_info "Updating system and installing core dependencies..."
sudo apt update || log_error "Failed to update apt."
sudo apt install -y python3-venv python3-dev libpq-dev nginx curl || log_error "Failed to install core dependencies."

# --- 2. Clone Repository (if not already present) ---
if [ ! -d "$PROJECT_DIR" ]; then
    log_info "Cloning repository into $PROJECT_DIR..."
    sudo mkdir -p "$PROJECT_DIR" || log_error "Failed to create project directory."
    sudo chown -R $USER:$USER "$PROJECT_DIR" || log_error "Failed to set ownership."
    git clone https://github.com/YOUR_GITHUB_REPO/satta-ai-bot.git "$PROJECT_DIR" || log_error "Failed to clone repository."
else
    log_warn "Project directory $PROJECT_DIR already exists. Skipping clone. Pulling latest changes..."
    cd "$PROJECT_DIR" || log_error "Failed to change directory to $PROJECT_DIR."
    git pull || log_error "Failed to pull latest changes."
fi
cd "$PROJECT_DIR" || log_error "Failed to change directory to $PROJECT_DIR."

# --- 3. Setup Virtual Environment ---
log_info "Setting up Python virtual environment..."
python3 -m venv "$VENV_DIR" || log_error "Failed to create virtual environment."
source "$VENV_DIR/bin/activate" || log_error "Failed to activate virtual environment."
pip install --upgrade pip || log_error "Failed to upgrade pip."
pip install -r requirements.txt || log_error "Failed to install Python dependencies."
deactivate || log_error "Failed to deactivate virtual environment."

# --- 4. Configure Environment Variables ---
log_info "Please create your .env file in $PROJECT_DIR."
log_info "You can copy .env.example and fill in the values:"
log_info "cp .env.example .env"
log_info "Edit .env with your actual production secrets."
log_warn "Ensure DB_URI is correct for your PostgreSQL database."
log_warn "Ensure TELEGRAM_BOT_TOKEN, PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET are set."
log_warn "Remember to replace 'YOUR_PUBLIC_DOMAIN_OR_IP' in app/handlers/pay.py with your actual domain/IP."
read -p "Press Enter once you have created and configured your .env file..."

# --- 5. Database Migrations (Alembic) ---
log_info "Initializing Alembic for database migrations..."
# Check if alembic.ini exists, if not, initialize
if [ ! -f "alembic.ini" ]; then
    log_info "alembic.ini not found. Initializing Alembic..."
    source "$VENV_DIR/bin/activate" || log_error "Failed to activate venv for alembic."
    alembic init -t async migrations || log_error "Failed to initialize Alembic."
    deactivate || log_error "Failed to deactivate venv after alembic init."
    log_warn "Alembic initialized. Please review 'alembic.ini' and 'migrations/env.py'."
    log_warn "You might need to adjust 'migrations/env.py' to import your models (from app.models import Base)."
    log_warn "And set 'target_metadata = Base.metadata'."
    read -p "Press Enter after reviewing Alembic configuration..."
fi

log_info "Running Alembic migrations..."
source "$VENV_DIR/bin/activate" || log_error "Failed to activate venv for migrations."
# Ensure env.py is configured to import Base from app.models and target_metadata is set
# You might need to manually edit migrations/env.py to point to your models
# Example: from app.models import Base; target_metadata = Base.metadata
alembic upgrade head || log_error "Failed to run Alembic migrations. Check alembic.ini and migrations/env.py."
deactivate || log_error "Failed to deactivate venv after migrations."
log_info "Database migrations applied successfully."

# --- 6. Install PM2 (if not already installed) ---
if ! command -v pm2 &> /dev/null; then
    log_info "PM2 not found. Installing PM2 globally..."
    sudo npm install pm2 -g || log_error "Failed to install PM2 globally."
    pm2 startup || log_error "Failed to generate PM2 startup script."
    log_info "PM2 installed. Please follow the instructions above to run the generated startup command."
    read -p "Press Enter after running the PM2 startup command..."
else
    log_info "PM2 is already installed."
fi

# --- 7. Create PM2 Configuration for Python ---
log_info "Creating PM2 configuration file (ecosystem.config.js)..."
cat << EOF > ecosystem.config.js
module.exports = {
  apps : [{
    name: "${SERVICE_NAME}",
    script: "${VENV_DIR}/bin/python3", # Path to python executable in venv
    args: "main.py",
    cwd: "${PROJECT_DIR}",
    instances: 1,
    autorestart: true,
    watch: false,
    ignore_watch: ["node_modules", "logs", ".git", ".env"],
    max_memory_restart: '1G',
    env: {
      NODE_ENV: "production",
    },
    env_production: {
      NODE_ENV: "production",
    },
    log_file: "logs/combined.log",
    error_file: "logs/error.log",
    out_file: "logs/out.log",
    merge_logs: true,
    time: true,
  }]
};
EOF
log_info "ecosystem.config.js created."

# --- 8. Start Application with PM2 ---
log_info "Starting application with PM2..."
pm2 start ecosystem.config.js || log_error "Failed to start application with PM2."
pm2 save || log_error "Failed to save PM2 process list."
log_info "Application started and saved with PM2. It will restart automatically on reboot."

# --- 9. Setup Nginx as a Reverse Proxy (Optional but Recommended for Flask) ---
log_info "Setting up Nginx as a reverse proxy for Flask (optional but recommended)..."
sudo rm -f /etc/nginx/sites-enabled/default # Remove default Nginx config

cat << EOF | sudo tee /etc/nginx/sites-available/$SERVICE_NAME
server {
    listen 80;
    server_name YOUR_PUBLIC_DOMAIN_OR_IP; # Replace with your domain or IP

    location / {
        proxy_pass http://127.0.0.1:$FLASK_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/$SERVICE_NAME /etc/nginx/sites-enabled/ || log_error "Failed to create Nginx symlink."
sudo nginx -t &> /dev/null || log_error "Nginx configuration test failed. Check /etc/nginx/sites-available/$SERVICE_NAME."
sudo systemctl restart nginx || log_error "Failed to restart Nginx."
log_info "Nginx configured as a reverse proxy. Remember to replace 'YOUR_PUBLIC_DOMAIN_OR_IP' in the Nginx config."
log_info "You can now access your Flask app via HTTP on port 80."

# --- 10. Create systemd service file (Alternative to PM2, or for PM2 startup) ---
log_info "Creating systemd service file for PM2 startup (satta-ai-bot.service)..."
cat << EOF | sudo tee /etc/systemd/system/$SERVICE_NAME.service
[Unit]
Description=PM2 process manager for Node.js applications
After=network.target

[Service]
Type=forking
User=$USER
LimitNOFILE=infinity
LimitNPROC=infinity
LimitCORE=infinity
WorkingDirectory=${PROJECT_DIR}
ExecStart=/usr/bin/pm2 resurrect
ExecReload=/usr/bin/pm2 reload all
ExecStop=/usr/bin/pm2 kill
Environment=PATH=/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/usr/local/sbin
# If PM2 is installed in a specific user's npm global path, you might need to adjust PATH
# Example: Environment=PATH=/home/$USER/.nvm/versions/node/v18.17.0/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload || log_error "Failed to reload systemd daemon."
sudo systemctl enable $SERVICE_NAME || log_error "Failed to enable systemd service."
log_info "systemd service file created and enabled. PM2 will start on boot."
log_warn "Note: The systemd service here is primarily to ensure PM2 starts on boot and manages your Python app."
log_warn "If you prefer to manage the Python app directly with systemd without PM2, you would need a different ExecStart command."

log_info "Deployment preparation complete!"
log_info "Your application is running under PM2 and Nginx is configured."
log_info "Remember to replace 'YOUR_PUBLIC_DOMAIN_OR_IP' in app/handlers/pay.py and Nginx config."
log_info "To check PM2 status: pm2 list"
log_info "To view logs: pm2 logs $SERVICE_NAME"
