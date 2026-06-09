#!/usr/bin/env bash
# QuantForge — CentOS 8 deployment (simple, no fancy functions)
# Runs sequentially in a single shell. Does NOT use set -e to avoid subshell traps.

echo "================================================================"
echo " QuantForge deployment to /opt/quantforge (CentOS 8)"
echo "================================================================"

APP_DIR=/opt/quantforge
SVC_USER=nginx
MARKER=/tmp/qf_deploy_marker

echo "[1/10] installing build toolchain via dnf..."
dnf install -y --setopt=install_weak_deps=False \
    curl ca-certificates git wget tar gzip make gcc gcc-c++ \
    openssl-devel bzip2-devel libffi-devel zlib-devel xz-devel \
    readline-devel sqlite-devel ncurses-devel gdbm-devel \
    uuid-devel libuuid-devel tk-devel xz-libs nginx 2>&1 \
    | tail -n 5
echo "  [ok] toolchain"

echo "[2/10] installing Python 3.12 — source build (slow, ~5-15 min)..."
if command -v python3.12 >/dev/null 2>&1; then
    PY=python3.12
    echo "  already have python3.12"
elif [ -x /usr/local/bin/python3.12 ]; then
    PY=/usr/local/bin/python3.12
    echo "  already have /usr/local/bin/python3.12"
else
    PV=3.12.7
    cd /tmp
    if [ ! -f Python-$PV.tgz ]; then
        echo "  downloading Python $PV..."
        curl -fsSL -o Python-$PV.tgz https://www.python.org/ftp/python/$PV/Python-$PV.tgz
    fi
    echo "  extracting..."
    tar -xzf Python-$PV.tgz
    cd Python-$PV
    echo "  configure..."
    ./configure --prefix=/usr/local --enable-shared --with-system-ffi \
        > /tmp/py-configure.log 2>&1
    echo "  make -j$(nproc)..."
    make -j"$(nproc)" > /tmp/py-make.log 2>&1
    echo "  make altinstall..."
    make altinstall > /tmp/py-install.log 2>&1
    ldconfig
    if [ -x /usr/local/bin/python3.12 ]; then
        PY=/usr/local/bin/python3.12
        echo "  [ok] python installed"
    else
        echo "  !! python build failed — last 40 lines of make log:"
        tail -n 40 /tmp/py-make.log
        exit 1
    fi
fi
echo "  python: $($PY --version 2>&1)"

echo "[3/10] Node.js 20..."
if ! command -v node >/dev/null 2>&1 || [ "$(node -v | tr -d v | cut -d. -f1)" -lt 20 ]; then
    curl -fsSL https://rpm.nodesource.com/setup_20.x | bash - >/dev/null 2>&1
    dnf install -y nodejs >/dev/null 2>&1
fi
echo "  node: $(node -v)  npm: $(npm -v)"

echo "[4/10] starting nginx..."
systemctl enable --now nginx >/dev/null 2>&1
[ -f /etc/nginx/conf.d/welcome.conf ] && mv /etc/nginx/conf.d/welcome.conf /etc/nginx/conf.d/welcome.conf.disabled
echo "  [ok] nginx: $(nginx -v 2>&1)"

echo "[5/10] firewall + selinux..."
if systemctl is-active --quiet firewalld 2>/dev/null; then
    firewall-cmd --permanent --add-service=http  >/dev/null 2>&1
    firewall-cmd --permanent --add-service=https >/dev/null 2>&1
    firewall-cmd --reload >/dev/null 2>&1
    echo "  [ok] firewalld"
fi
if [ "$(getenforce 2>/dev/null)" = "Enforcing" ]; then
    setsebool -P httpd_can_network_connect 1
    setsebool -P httpd_can_network_relay   1
    echo "  [ok] selinux"
fi

echo "[6/10] preparing project dirs..."
mkdir -p $APP_DIR/data $APP_DIR/data/parquet $APP_DIR/data/cache $APP_DIR/logs
chown -R $SVC_USER:$SVC_USER $APP_DIR

echo "[7/10] python venv + deps..."
rm -rf $APP_DIR/.venv
$PY -m venv $APP_DIR/.venv || $PY -m venv --without-pip $APP_DIR/.venv
$APP_DIR/.venv/bin/pip install --upgrade pip setuptools wheel >/tmp/pip-upgrade.log 2>&1
$APP_DIR/.venv/bin/pip install uvicorn fastapi
$APP_DIR/.venv/bin/pip install -e $APP_DIR[api]
echo "  [ok] python deps"

echo "[8/10] building frontend (Vue3 + Vite)..."
cd $APP_DIR/web
npm install --no-audit --no-fund >/tmp/npm-install.log 2>&1
npm run build >/tmp/npm-build.log 2>&1 || { echo "  !! build failed — last 30 lines:"; tail -n 30 /tmp/npm-build.log; exit 2; }
echo "  [ok] frontend built at $APP_DIR/web/dist"

echo "[9/10] .env + systemd + nginx..."
if [ ! -f $APP_DIR/.env ]; then
    cp $APP_DIR/.env.example $APP_DIR/.env
    SECRET=$($APP_DIR/.venv/bin/python -c 'import secrets;print(secrets.token_hex(32))')
    echo "" >> $APP_DIR/.env
    echo "SECRET_KEY=$SECRET" >> $APP_DIR/.env
fi
chown $SVC_USER:$SVC_USER $APP_DIR/.env
chmod 600 $APP_DIR/.env

# systemd unit (nginx user)
cat > /etc/systemd/system/quantforge.service <<'EOF'
[Unit]
Description=QuantForge
After=network.target

[Service]
Type=simple
User=nginx
Group=nginx
WorkingDirectory=/opt/quantforge
Environment=PATH=/opt/quantforge/.venv/bin
ExecStart=/opt/quantforge/.venv/bin/uvicorn quantforge.api.app:app --host 127.0.0.1 --port 8000 --workers 2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now quantforge.service || systemctl restart quantforge.service
sleep 3
if systemctl is-active --quiet quantforge.service; then
    echo "  [ok] quantforge.service running"
else
    echo "  !! service failed — journal:"
    journalctl -u quantforge.service -n 40 --no-pager
fi

# nginx site
cat > /etc/nginx/conf.d/quantforge.conf <<'EOF'
server {
    listen 80;
    server_name _;
    client_max_body_size 50M;

    gzip on;
    gzip_types text/plain text/css application/javascript application/json image/svg+xml;

    location /api {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }
    location /openapi.json { proxy_pass http://127.0.0.1:8000; }
    location /docs { proxy_pass http://127.0.0.1:8000; }
    location /redoc { proxy_pass http://127.0.0.1:8000; }

    location /assets/ {
        root /opt/quantforge/web/dist;
        expires 30d;
    }
    location / {
        root /opt/quantforge/web/dist;
        try_files $uri $uri/ /index.html;
        index index.html;
    }
}
EOF
# selinux context on static assets
[ -x /usr/sbin/semanage ] && semanage fcontext -a -t httpd_sys_content_t '/opt/quantforge/web/dist(/.*)?' 2>/dev/null
[ -x /usr/sbin/restorecon ] && restorecon -R /opt/quantforge/web/dist 2>/dev/null

nginx -t >/dev/null 2>&1 && systemctl reload nginx || { echo "  !! nginx config:"; nginx -t; }
echo "  [ok] nginx configured"

echo "[10/10] verification..."
PUBLIC=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo "  backend health: $(curl -sS http://127.0.0.1:8000/api/system/health 2>&1)"
echo "  frontend HTTP : $(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1/ 2>&1)"
echo "  public URL    : http://$PUBLIC"
echo "  service       : systemctl status quantforge.service"
echo "  logs          : journalctl -u quantforge.service -f"
echo "=================================================================="
echo " Deploy complete."
echo "=================================================================="
