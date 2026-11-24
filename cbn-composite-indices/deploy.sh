#!/usr/bin/env bash
#
# Deploy cbn-composite-indices on this host.
#
# Current mode: IP + port access (http://<server-ip>:8010).
# DNS/TLS for cbn.hudson10data.com is intentionally TODO; see DEPLOYMENT.md.
#
# Usage:
#   sudo ./deploy.sh
#   sudo PUBLIC_PORT=8010 ./deploy.sh
#

set -euo pipefail

PROJECT_NAME="cbn-composite-indices"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${DEPLOY_DIR:-/var/www/${PROJECT_NAME}}"
REFERENCE_DIR="${REFERENCE_DIR:-/var/www/cbn-reference}"
APP_HOST_PORT="${APP_HOST_PORT:-8000}"
PUBLIC_PORT="${PUBLIC_PORT:-8010}"
DOMAIN="${DOMAIN:-}"
EMAIL="${EMAIL:-}"

log() { echo "[deploy] $*"; }
fail() { echo "[deploy] ERROR: $*" >&2; exit 1; }
require_command() { command -v "$1" >/dev/null 2>&1 || fail "$1 is required but not installed"; }

if [[ $EUID -ne 0 ]]; then
    fail "Run as root (sudo ./deploy.sh)"
fi

for cmd in docker rsync openssl curl; do
    require_command "$cmd"
done
docker compose version >/dev/null 2>&1 || fail "docker compose plugin is required"

SOURCE_DIR="$(realpath "$SOURCE_DIR")"
DEPLOY_DIR="$(realpath -m "$DEPLOY_DIR")"
REFERENCE_DIR="$(realpath -m "$REFERENCE_DIR")"

log "Source: ${SOURCE_DIR}"
log "Deploy dir: ${DEPLOY_DIR}"
log "Reference data: ${REFERENCE_DIR}"
log "Public port: ${PUBLIC_PORT} -> app on 127.0.0.1:${APP_HOST_PORT}"

# --------------------------------------------------------------------------- #
# 1. Sync source into /var/www (never clone a placeholder repo)
# --------------------------------------------------------------------------- #
if [[ "$SOURCE_DIR" == "$DEPLOY_DIR" ]]; then
    log "Source and deploy directory are the same; skipping sync"
else
    install -d -m 0755 "$DEPLOY_DIR"
    rsync -a --delete \
        --exclude='.git/' \
        --exclude='.env' \
        --exclude='__pycache__/' \
        --exclude='*.pyc' \
        --exclude='.pytest_cache/' \
        --exclude='.venv/' \
        --exclude='instance/' \
        --exclude='data/' \
        --exclude='*.log' \
        "$SOURCE_DIR/" "$DEPLOY_DIR/"
    log "Synced source into ${DEPLOY_DIR}"
fi

# --------------------------------------------------------------------------- #
# 2. QA sample datasets, mounted read-only at /reference in containers
# --------------------------------------------------------------------------- #
install -d -m 0755 "$REFERENCE_DIR"
REFERENCE_SOURCE_DIR="${REFERENCE_SOURCE_DIR:-$(dirname "$SOURCE_DIR")}"
if [[ ! -d "$REFERENCE_SOURCE_DIR" || ! -f "$REFERENCE_SOURCE_DIR/bci_simulated_dataset.csv" ]]; then
    REFERENCE_SOURCE_DIR="/opt/data-science-proj"
fi
for name in \
    bci_simulated_dataset.csv \
    cci_simulated_dataset.csv \
    hfci_simulated_dataset.csv \
    ipi_simulated_dataset.csv \
    lmci_simulated_dataset.csv
do
    if [[ -f "$REFERENCE_SOURCE_DIR/$name" ]]; then
        install -m 0644 "$REFERENCE_SOURCE_DIR/$name" "$REFERENCE_DIR/$name"
    else
        fail "Reference dataset $name not found in $REFERENCE_SOURCE_DIR"
    fi
done
log "Reference datasets ready in ${REFERENCE_DIR}"

# --------------------------------------------------------------------------- #
# 3. Production .env (created once, then left alone)
# --------------------------------------------------------------------------- #
ENV_FILE="${DEPLOY_DIR}/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    cp "${DEPLOY_DIR}/.env.example" "$ENV_FILE"
    SECRET_KEY="$(openssl rand -hex 32)"
    DB_PASSWORD="$(openssl rand -hex 16)"
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|" "$ENV_FILE"
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${DB_PASSWORD}|" "$ENV_FILE"
    sed -i "s|^FLASK_ENV=.*|FLASK_ENV=production|" "$ENV_FILE"
    sed -i "s|^WEB_PORT=.*|WEB_PORT=${APP_HOST_PORT}|" "$ENV_FILE"
    if grep -q '^REFERENCE_DIR=' "$ENV_FILE"; then
        sed -i "s|^REFERENCE_DIR=.*|REFERENCE_DIR=${REFERENCE_DIR}|" "$ENV_FILE"
    else
        printf '\nREFERENCE_DIR=%s\n' "$REFERENCE_DIR" >> "$ENV_FILE"
    fi
    log "Created ${ENV_FILE} with generated secrets"
else
    log "${ENV_FILE} exists; leaving it untouched"
    if ! grep -q '^REFERENCE_DIR=' "$ENV_FILE"; then
        printf '\nREFERENCE_DIR=%s\n' "$REFERENCE_DIR" >> "$ENV_FILE"
    fi
fi
chmod 600 "$ENV_FILE"

# --------------------------------------------------------------------------- #
# 4. systemd unit for the whole Compose stack
# --------------------------------------------------------------------------- #
UNIT_FILE="/etc/systemd/system/${PROJECT_NAME}.service"
cat > "$UNIT_FILE" <<EOF
[Unit]
Description=CBN Composite Indices Docker Compose Application
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${DEPLOY_DIR}
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
ExecReload=/usr/bin/docker compose restart
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
log "Installed ${UNIT_FILE}"

# --------------------------------------------------------------------------- #
# 5. Build and start
# --------------------------------------------------------------------------- #
cd "$DEPLOY_DIR"
log "Building images"
docker compose build

systemctl enable "${PROJECT_NAME}.service" >/dev/null
if systemctl is-active --quiet "${PROJECT_NAME}.service"; then
    systemctl restart "${PROJECT_NAME}.service"
else
    systemctl start "${PROJECT_NAME}.service"
fi

log "Waiting for app health on 127.0.0.1:${APP_HOST_PORT}"
healthy=0
for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${APP_HOST_PORT}/health" >/dev/null 2>&1; then
        healthy=1
        break
    fi
    sleep 2
done
[[ "$healthy" -eq 1 ]] || fail "App did not become healthy; check: docker compose -f ${DEPLOY_DIR}/docker-compose.yml logs --tail=100"
log "App health: $(curl -fsS "http://127.0.0.1:${APP_HOST_PORT}/health")"

# --------------------------------------------------------------------------- #
# 6. Nginx reverse proxy on a dedicated port; other vhosts are untouched
# --------------------------------------------------------------------------- #
NGINX_CONF="/etc/nginx/sites-available/${PROJECT_NAME}"
cat > "$NGINX_CONF" <<EOF
# Deployed for IP/port access. The default Nginx site and other vhosts are untouched.
# TODO(DNS/TLS): add DNS for cbn.hudson10data.com, issue a certificate, then
# replace this server with a 443 ssl vhost for that hostname. See DEPLOYMENT.md.
server {
    listen ${PUBLIC_PORT};
    listen [::]:${PUBLIC_PORT};
    server_name _;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:${APP_HOST_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
    }
}
EOF
ln -sfn "$NGINX_CONF" "/etc/nginx/sites-enabled/${PROJECT_NAME}"
nginx -t
systemctl reload nginx
log "Installed Nginx config ${NGINX_CONF}"

# --------------------------------------------------------------------------- #
# 7. Done; DNS/TLS is deliberately left as a TODO
# --------------------------------------------------------------------------- #
SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
log "Deployment complete: http://${SERVER_IP:-<server-ip>}:${PUBLIC_PORT}"
log "Verify: curl -fsS http://127.0.0.1:${PUBLIC_PORT}/health"
log "Service: systemctl status ${PROJECT_NAME}.service"
log "TODO(DNS/TLS): DOMAIN=${DOMAIN:-cbn.hudson10data.com} EMAIL=${EMAIL:-<email>} -- see DEPLOYMENT.md"
