#!/usr/bin/env bash
#
# Deploy cbn-composite-indices behind Nginx on a Linux server.
#
# This script is meant to be copied to the target server and run as root
# (or a user with passwordless sudo). It will:
#   1. Install Docker and Docker Compose if missing.
#   2. Clone (or update) the project into /var/www/cbn-composite-indices.
#   3. Create / verify a production-ready .env file.
#   4. Build and start the Docker Compose stack.
#   5. Install and enable an Nginx reverse-proxy config.
#
# Usage:
#   chmod +x deploy.sh
#   sudo ./deploy.sh
#

set -euo pipefail

PROJECT_NAME="cbn-composite-indices"
DEPLOY_DIR="/var/www/${PROJECT_NAME}"
REPO_URL="https://github.com/YOUR_ORG/${PROJECT_NAME}.git"
DOMAIN="${DOMAIN:-}"
EMAIL="${EMAIL:-}"

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
log() { echo "[deploy] $*"; }
fail() { echo "[deploy] ERROR: $*" >&2; exit 1; }

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "$1 is required but not installed"
}

# --------------------------------------------------------------------------- #
# 0. Preflight
# --------------------------------------------------------------------------- #
if [[ $EUID -ne 0 ]]; then
    fail "Please run this script as root or with sudo"
fi

log "Starting deployment of ${PROJECT_NAME}..."

# --------------------------------------------------------------------------- #
# 1. Install Docker + Docker Compose (Ubuntu/Debian)
# --------------------------------------------------------------------------- #
if ! command -v docker >/dev/null 2>&1; then
    log "Installing Docker..."
    apt-get update
    apt-get install -y ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

if ! command -v docker >/dev/null 2>&1; then
    fail "Docker installation failed"
fi

# Prefer the plugin form of compose; fall back to the standalone binary.
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    log "Installing Docker Compose plugin..."
    apt-get install -y docker-compose-plugin
    COMPOSE="docker compose"
fi

log "Using compose command: ${COMPOSE}"

# --------------------------------------------------------------------------- #
# 2. Clone or update the project
# --------------------------------------------------------------------------- #
log "Deploying project to ${DEPLOY_DIR}..."
mkdir -p /var/www

if [[ -d "${DEPLOY_DIR}/.git" ]]; then
    log "Existing repository found; pulling latest changes..."
    cd "${DEPLOY_DIR}"
    git pull origin main
else
    log "Cloning repository..."
    git clone "${REPO_URL}" "${DEPLOY_DIR}"
    cd "${DEPLOY_DIR}"
fi

# --------------------------------------------------------------------------- #
# 3. Environment configuration
# --------------------------------------------------------------------------- #
if [[ ! -f .env ]]; then
    log "Creating .env from .env.example..."
    cp .env.example .env
    SECRET_KEY=$(openssl rand -hex 32)
    DB_PASSWORD=$(openssl rand -hex 16)
    sed -i "s|SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|" .env
    sed -i "s|POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${DB_PASSWORD}|" .env
    log "Generated SECRET_KEY and POSTGRES_PASSWORD in .env"
else
    log ".env already exists; leaving it untouched"
fi

# --------------------------------------------------------------------------- #
# 4. Build and start the stack
# --------------------------------------------------------------------------- #
log "Building and starting Docker Compose stack..."
${COMPOSE} down
${COMPOSE} up -d --build

# Wait for services to be healthy
log "Waiting for services to become healthy..."
sleep 5
${COMPOSE} ps

# --------------------------------------------------------------------------- #
# 5. Nginx reverse proxy
# --------------------------------------------------------------------------- #
log "Configuring Nginx..."
apt-get install -y nginx

NGINX_CONF="/etc/nginx/sites-available/${PROJECT_NAME}"

# Use a placeholder domain if none was supplied.
SERVER_NAME="${DOMAIN:-_}"

cat > "${NGINX_CONF}" <<EOF
server {
    listen 80;
    server_name ${SERVER_NAME};

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
    }
}
EOF

if [[ -f /etc/nginx/sites-enabled/default ]]; then
    rm /etc/nginx/sites-enabled/default
fi

ln -sf "${NGINX_CONF}" "/etc/nginx/sites-enabled/${PROJECT_NAME}"

nginx -t && systemctl reload nginx

# --------------------------------------------------------------------------- #
# 6. Optional: Certbot / HTTPS
# --------------------------------------------------------------------------- #
if [[ -n "${DOMAIN}" && -n "${EMAIL}" ]]; then
    log "Attempting to obtain TLS certificate for ${DOMAIN}..."
    apt-get install -y certbot python3-certbot-nginx
    certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m "${EMAIL}" --redirect
fi

# --------------------------------------------------------------------------- #
# 7. Make this script executable and keep a copy in the deploy directory
# --------------------------------------------------------------------------- #
SCRIPT_SRC="${DEPLOY_DIR}/deploy.sh"
if [[ -f deploy.sh && "${SCRIPT_SRC}" != "$(realpath "$0")" ]]; then
    cp deploy.sh "${SCRIPT_SRC}"
fi
chmod +x "${SCRIPT_SRC}"

log "Deployment complete."
log "App should be reachable at: http://${DOMAIN:-your-server-ip}"
log "Verify with: cd ${DEPLOY_DIR} && ${COMPOSE} ps"