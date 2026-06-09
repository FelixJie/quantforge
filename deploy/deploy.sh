#!/usr/bin/env bash
#
# QuantForge one-click deployment script (Ubuntu 22.04 / Debian 12+)
#
# Usage:
#   sudo bash deploy/deploy.sh                 # first-time install
#   sudo bash deploy/deploy.sh --update        # pull code & restart
#
# Result:
#   - Backend:  FastAPI + uvicorn, systemd service "quantforge", 127.0.0.1:8000
#   - Frontend: Vue3 + Vite  static build, served by Nginx on port 80
#   - Nginx:    reverse proxy /api -> :8000, SPA fallback to /opt/quantforge/web/dist
#   - DB:       SQLite at /opt/quantforge/data/quantforge.db
#
# Requirements (auto-installed if missing):
#   python3.12+ | python3-pip | python3-venv | nodejs 20+ | npm | nginx | git
#

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_NAME="quantforge"
INSTALL_DIR="/opt/quantforge"
SERVICE_USER="www-data"
BACKEND_PORT=8000
REPO_URL="${REPO_URL:-}"   # set this env var to git-pull instead of local copy
BRANCH="${BRANCH:-main}"
LOG_PREFIX="[quantforge-deploy]"

UPDATE_MODE=0
for arg in "$@"; do
    case "$arg" in
        --update) UPDATE_MODE=1 ;;
        -h|--help)
            echo "Usage: sudo bash deploy/deploy.sh [--update]"; exit 0 ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "$LOG_PREFIX $(date '+%H:%M:%S') $*"; }
ok()   { log "✔  $*"; }
info() { log "── $*"; }
warn() { log "⚠  $*" >&2; }
die()  { log "✖  $*" >&2; exit 1; }

# must run as root
if [ "$(id -u)" -ne 0 ]; then
    die "Please run with sudo or as root."
fi

# detect package manager
if command -v apt-get >/dev/null 2>&1; then
    PKG="apt-get"
elif command -v dnf >/dev/null 2>&1; then
    PKG="dnf"
elif command -v yum >/dev/null 2>&1; then
    PKG="yum"
else
    die "Unsupported distribution — no apt-get/dnf/yum found."
fi
info "Package manager: $PKG"

# ---------------------------------------------------------------------------
# Step 1 — system dependencies
# ---------------------------------------------------------------------------
info "(1/7) Installing system dependencies ..."
export DEBIAN_FRONTEND=noninteractive
$PKG update -y >/dev/null

install_pkg() {
    for pkg in "$@"; do
        if ! dpkg -s "$pkg" >/dev/null 2>&1; then
            info "  installing $pkg"
            $PKG install -y "$pkg" >/dev/null || warn "failed to install $pkg"
        fi
    done
}

install_pkg curl ca-certificates gnupg lsb-release software-properties-common
install_pkg python3 python3-pip python3-venv
install_pkg nginx git

# ensure python3 points to 3.12+
PY_MINOR=$(python3 -c 'import sys;print(sys.version_info.minor)' 2>/dev/null || echo 0)
if [ "$PY_MINOR" -lt 12 ]; then
    info "  system python3 is 3.$PY_MINOR — installing python3.12 from deadsnakes"
    add-apt-repository -y ppa:deadsnakes/ppa >/dev/null 2>&1 || true
    $PKG install -y python3.12 python3.12-venv python3.12-dev >/dev/null
    PY_BIN=python3.12
else
    PY_BIN=python3
fi
ok "Python: $($PY_BIN --version)"

# Node.js 20.x (for Vite build)
if ! command -v node >/dev/null || [ "$(node -v | sed 's/v//' | cut -d. -f1)" -lt 20 ]; then
    info "  installing Node.js 20.x"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
    $PKG install -y nodejs >/dev/null
fi
ok "Node.js: $(node -v)  npm: $(npm -v)"

# ---------------------------------------------------------------------------
# Step 2 — code placement
# ---------------------------------------------------------------------------
info "(2/7) Placing code into $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -n "$REPO_URL" ]; then
    if [ -d "$INSTALL_DIR/.git" ]; then
        info "  git pull ($BRANCH)"
        (cd "$INSTALL_DIR" && git fetch --all && git reset --hard "origin/$BRANCH")
    else
        info "  git clone $REPO_URL ($BRANCH)"
        rm -rf "$INSTALL_DIR"
        git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
    fi
else
    info "  copying project from $PROJECT_ROOT"
    # copy everything except volatile dirs
    rsync -a --delete \
        --exclude='.venv' --exclude='venv' --exclude='node_modules' \
        --exclude='web/dist' --exclude='data/parquet' --exclude='data/cache' \
        --exclude='.git' --exclude='__pycache__' --exclude='*.log' \
        "$PROJECT_ROOT/" "$INSTALL_DIR/"
fi

# ensure required data dirs exist
mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/data/parquet" "$INSTALL_DIR/data/cache" "$INSTALL_DIR/logs"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"
ok "code deployed to $INSTALL_DIR"

# ---------------------------------------------------------------------------
# Step 3 — Python virtualenv & dependencies
# ---------------------------------------------------------------------------
info "(3/7) Creating Python virtualenv & installing deps ..."
VENV="$INSTALL_DIR/.venv"
if [ ! -d "$VENV" ]; then
    $PY_BIN -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip setuptools wheel >/dev/null
"$VENV/bin/pip" install -e "$INSTALL_DIR[api]"
# extras
"$VENV/bin/pip" install uvicorn gunicorn
ok "Python deps installed"

# ---------------------------------------------------------------------------
# Step 4 — frontend build
# ---------------------------------------------------------------------------
info "(4/7) Building frontend (Vue3 + Vite) ..."
cd "$INSTALL_DIR/web"
if [ ! -d node_modules ] || [ "$UPDATE_MODE" -eq 1 ]; then
    npm ci --no-audit --no-fund || npm install --no-audit --no-fund
fi
npm run build
ok "frontend built at $INSTALL_DIR/web/dist"

# ---------------------------------------------------------------------------
# Step 5 — env file
# ---------------------------------------------------------------------------
info "(5/7) Writing .env file ..."
ENV_FILE="$INSTALL_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$INSTALL_DIR/.env.example" "$ENV_FILE"
    # generate a random SECRET_KEY if missing
    if ! grep -q '^SECRET_KEY=' "$ENV_FILE"; then
        SECRET=$(openssl rand -hex 32 2>/dev/null || "$VENV/bin/python" -c 'import secrets;print(secrets.token_hex(32))')
        echo "" >> "$ENV_FILE"
        echo "# Auto-generated at install time" >> "$ENV_FILE"
        echo "SECRET_KEY=$SECRET" >> "$ENV_FILE"
    fi
fi
chown "$SERVICE_USER":"$SERVICE_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"
ok "env file ready at $ENV_FILE"

# ---------------------------------------------------------------------------
# Step 6 — systemd service
# ---------------------------------------------------------------------------
info "(6/7) Installing systemd unit ..."
UNIT_FILE="/etc/systemd/system/quantforge.service"
# patch user / paths in the unit file to match this install
sed -e "s|User=www-data|User=$SERVICE_USER|" \
    -e "s|Group=www-data|Group=$SERVICE_USER|" \
    -e "s|/opt/quantforge|$INSTALL_DIR|g" \
    "$INSTALL_DIR/deploy/quantforge.service" > "$UNIT_FILE"
systemctl daemon-reload
systemctl enable quantforge.service
systemctl restart quantforge.service
# wait briefly and confirm
sleep 3
if systemctl is-active --quiet quantforge.service; then
    ok "systemd service quantforge.service is running"
else
    warn "service failed to start — check: journalctl -u quantforge.service -n 50"
    journalctl -u quantforge.service -n 30 --no-pager | tail -n 30 || true
fi

# ---------------------------------------------------------------------------
# Step 7 — nginx
# ---------------------------------------------------------------------------
info "(7/7) Configuring Nginx ..."
NGINX_CONF="/etc/nginx/sites-available/quantforge"
sed -e "s|/opt/quantforge|$INSTALL_DIR|g" "$INSTALL_DIR/deploy/nginx.conf" > "$NGINX_CONF"
# remove default nginx site if present
rm -f /etc/nginx/sites-enabled/default
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/quantforge
nginx -t && systemctl reload nginx
ok "Nginx configured and reloaded"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "================================================================"
echo " QuantForge deployment complete."
echo "================================================================"
echo "  Installation dir : $INSTALL_DIR"
echo "  Backend          : http://127.0.0.1:$BACKEND_PORT  (systemd: quantforge.service)"
echo "  Frontend + API   : http://$(hostname -I | awk '{print $1}') (port 80)"
echo "  Logs             : journalctl -u quantforge.service -f"
echo "  Config           : $INSTALL_DIR/.env"
echo
echo "  Useful commands:"
echo "    sudo systemctl status quantforge.service"
echo "    sudo systemctl restart quantforge.service"
echo "    sudo journalctl -u quantforge.service -n 100"
echo "    sudo bash $INSTALL_DIR/deploy/deploy.sh --update"
echo "================================================================"
