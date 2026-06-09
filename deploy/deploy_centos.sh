#!/usr/bin/env bash
#
# QuantForge deployment — robust CentOS 8/9 version.
# Fallback chain for Python 3.12: Remi repo -> direct RPM download -> source build.
#
set -euo pipefail

APP_NAME="quantforge"
INSTALL_DIR="/opt/quantforge"
SERVICE_USER="nginx"
BACKEND_PORT=8000
PY_TARGET="3.12"
LOG_PREFIX="[quantforge-deploy]"

info() { echo "$LOG_PREFIX -- $*" >&2; }
ok()   { echo "$LOG_PREFIX OK $*" >&2; }
warn() { echo "$LOG_PREFIX !! $*" >&2; }
die()  { echo "$LOG_PREFIX FAIL $*" >&2; exit 1; }

# -------- pick package manager --------
if command -v dnf >/dev/null 2>&1; then
    PKG=dnf
elif command -v yum >/dev/null 2>&1; then
    PKG=yum
else
    die "no dnf/yum found"
fi
info "package manager: $PKG"

# -------- 1. build toolchain (for Python source build fallback) --------
info "(1/8) installing build toolchain and base packages ..."
$PKG install -y --setopt=install_weak_deps=False \
    curl ca-certificates git wget tar gzip make gcc gcc-c++ \
    openssl-devel bzip2-devel libffi-devel zlib-devel xz-devel \
    readline-devel sqlite-devel ncurses-devel gdbm-devel \
    uuid-devel libuuid-devel tk-devel xz-libs \
    >/dev/null 2>&1 || warn "some build deps not installed"
$PKG install -y nginx >/dev/null 2>&1 || true
ok "build toolchain ready"

# -------- 2. install python 3.12 --------
info "(2/8) installing python $PY_TARGET ..."

install_python_from_remi() {
    info "  method A: remi repo"
    OS_VER=$(rpm -E %{rhel} 2>/dev/null)
    [ -z "$OS_VER" ] || [ "$OS_VER" = "%{rhel}" ] && OS_VER=8
    $PKG install -y https://rpms.remirepo.net/enterprise/remi-release-"$OS_VER".rpm >/dev/null 2>&1 || return 1
    $PKG makecache >/dev/null 2>&1 || true
    $PKG install -y --enablerepo=remi python3.12 python3.12-pip python3.12-devel >/dev/null 2>&1 || return 1
    command -v python3.12 >/dev/null 2>&1 && echo "python3.12" && return 0
    return 1
}

install_python_from_source() {
    info "  method B: build from source (takes ~5 minutes on 1 vCPU)"
    local VER="3.12.7"
    local URL="https://www.python.org/ftp/python/$VER/Python-$VER.tgz"
    local SRC="/tmp/Python-$VER"
    rm -rf "$SRC"
    mkdir -p "$SRC"
    info "    downloading $URL ..."
    curl -fsSL "$URL" -o /tmp/Python-"$VER".tgz || { warn "download failed"; return 1; }
    info "    extracting ..."
    tar -xzf /tmp/Python-"$VER".tgz -C /tmp
    cd "$SRC"
    info "    configuring (optimizations disabled to speed up) ..."
    ./configure --prefix=/usr/local --enable-shared --with-system-ffi --with-ensurepip=install --without-ensurepip=no >/tmp/py-configure.log 2>&1 \
        || ./configure --prefix=/usr/local --enable-shared --with-system-ffi >/tmp/py-configure.log 2>&1 \
        || { warn "configure failed"; tail -n 30 /tmp/py-configure.log; return 1; }
    info "    building with -j$(nproc) ..."
    make -j"$(nproc)" >/tmp/py-make.log 2>&1 || { warn "make failed"; tail -n 40 /tmp/py-make.log; return 1; }
    info "    installing ..."
    make altinstall >/tmp/py-install.log 2>&1 || { warn "make install failed"; tail -n 40 /tmp/py-install.log; return 1; }
    ldconfig
    # binary is /usr/local/bin/python3.12
    if [ -x /usr/local/bin/python3.12 ]; then
        echo "/usr/local/bin/python3.12"
        return 0
    fi
    return 1
}

PY_BIN=""
# try system-installed python3.12 first
if command -v python3.12 >/dev/null 2>&1; then
    PY_BIN=python3.12
fi
# otherwise try remi
if [ -z "$PY_BIN" ]; then
    result=$(install_python_from_remi) || true
    [ -n "$result" ] && PY_BIN="$result"
fi
# otherwise build from source
if [ -z "$PY_BIN" ]; then
    result=$(install_python_from_source) || true
    [ -n "$result" ] && PY_BIN="$result"
fi
# last resort: system python3 if >= 3.8
if [ -z "$PY_BIN" ]; then
    if command -v python3 >/dev/null 2>&1; then
        minor=$("$PY_BIN" -c 'import sys;print(sys.version_info.minor)' 2>/dev/null || echo 0)
        if [ "$minor" -ge 8 ]; then
            warn "falling back to system python3"
            PY_BIN=python3
        fi
    fi
fi

if [ -z "$PY_BIN" ]; then
    die "could not install python 3.12+ — see logs above"
fi
PY_VERSION=$("$PY_BIN" --version 2>&1)
ok "python ready: $PY_VERSION ($PY_BIN)"

# -------- 3. Node.js 20 --------
info "(3/8) installing Node.js 20 ..."
if ! command -v node >/dev/null 2>&1 || [ "$(node -v | tr -d 'v' | cut -d. -f1)" -lt 20 ]; then
    curl -fsSL https://rpm.nodesource.com/setup_20.x | bash - >/dev/null 2>&1 || true
    $PKG install -y nodejs >/dev/null 2>&1 || true
fi
ok "node: $(node -v 2>&1)  npm: $(npm -v 2>&1)"

# -------- 4. Nginx --------
info "(4/8) starting Nginx ..."
systemctl enable --now nginx >/dev/null 2>&1 || true
if [ -f /etc/nginx/conf.d/welcome.conf ]; then
    mv /etc/nginx/conf.d/welcome.conf /etc/nginx/conf.d/welcome.conf.disabled
fi
ok "nginx: $(nginx -v 2>&1)"

# -------- 5. firewall + SELinux --------
info "(5/8) firewall + selinux ..."
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --add-service=http  >/dev/null 2>&1 || true
    firewall-cmd --permanent --add-service=https >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
    ok "firewalld: http/https open"
fi
if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce)" = "Enforcing" ]; then
    setsebool -P httpd_can_network_connect 1   >/dev/null 2>&1 || true
    setsebool -P httpd_can_network_relay   1   >/dev/null 2>&1 || true
    ok "selinux: httpd_can_network_connect=1"
fi

# -------- 6. prepare install dir --------
info "(6/8) preparing $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/data/parquet" "$INSTALL_DIR/data/cache" "$INSTALL_DIR/logs"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"
# selinux context for nginx-served static files
if command -v semanage >/dev/null 2>&1; then
    semanage fcontext -a -t httpd_sys_content_t "$INSTALL_DIR/web/dist(/.*)?" 2>/dev/null || true
    [ -d "$INSTALL_DIR/web/dist" ] && restorecon -R "$INSTALL_DIR/web/dist" 2>/dev/null || true
fi
ok "install dir ready"

# -------- 7. venv + python deps --------
info "(7/8) python virtualenv & dependencies ..."
VENV="$INSTALL_DIR/.venv"
rm -rf "$VENV"
"$PY_BIN" -m venv "$VENV" || "$PY_BIN" -m venv --without-pip "$VENV" || {
    # CentOS 8 python36 can lack venv module — try ensurepip / manual bootstrap
    "$PY_BIN" -m ensurepip --upgrade 2>/dev/null || true
    "$PY_BIN" -m pip install --user virtualenv 2>/dev/null || true
    "$PY_BIN" -m virtualenv "$VENV" 2>/dev/null || die "venv creation failed"
}
"$VENV/bin/pip" install --upgrade pip setuptools wheel >/tmp/pip-upgrade.log 2>&1 \
    || warn "pip upgrade failed (continuing)"
info "  installing quantforge[api] + uvicorn ..."
"$VENV/bin/pip" install uvicorn fastapi
"$VENV/bin/pip" install -e "$INSTALL_DIR[api]"
ok "python deps installed"

# efinance 在运行时会往自身包目录写 data/ 缓存；服务以 $SERVICE_USER 身份跑，
# 而包是 root(pip) 装的 → 否则会 [Errno 13] Permission denied，导致 overview/基本面 503。
EF_DIR=$("$VENV/bin/python" -c 'import os,efinance;print(os.path.dirname(efinance.__file__))' 2>/dev/null || true)
if [ -n "$EF_DIR" ] && [ -d "$EF_DIR" ]; then
    mkdir -p "$EF_DIR/data"
    chown -R "$SERVICE_USER":"$SERVICE_USER" "$EF_DIR/data" "$EF_DIR/config" 2>/dev/null || true
    chmod -R u+rwX "$EF_DIR/data" "$EF_DIR/config" 2>/dev/null || true
    ok "efinance cache dir writable by $SERVICE_USER"
fi

# -------- 8. frontend build --------
info "(8/8) building frontend ..."
cd "$INSTALL_DIR/web"
npm install --no-audit --no-fund --silent 2>&1 | tail -n 20 || true
npm run build 2>&1 | tail -n 30 || true
ok "frontend built"

# -------- post: env file, systemd, nginx --------
info "post-install: .env + systemd + nginx ..."
ENV_FILE="$INSTALL_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$INSTALL_DIR/.env.example" "$ENV_FILE"
    SECRET=$("$VENV/bin/python" -c 'import secrets;print(secrets.token_hex(32))')
    { echo ""; echo "SECRET_KEY=$SECRET"; } >> "$ENV_FILE"
fi
chown "$SERVICE_USER":"$SERVICE_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

# install systemd unit
UNIT_FILE="/etc/systemd/system/quantforge.service"
sed -e "s|User=www-data|User=$SERVICE_USER|" \
    -e "s|Group=www-data|Group=$SERVICE_USER|" \
    -e "s|/opt/quantforge|$INSTALL_DIR|g" \
    "$INSTALL_DIR/deploy/quantforge.service" > "$UNIT_FILE"
systemctl daemon-reload
systemctl enable --now quantforge.service || systemctl restart quantforge.service
sleep 3
if systemctl is-active --quiet quantforge.service; then
    ok "quantforge.service is running"
else
    warn "service did not start — showing journal:"
    journalctl -u quantforge.service -n 40 --no-pager || true
fi

# nginx site
NGINX_CONF="/etc/nginx/conf.d/quantforge.conf"
sed -e "s|/opt/quantforge|$INSTALL_DIR|g" "$INSTALL_DIR/deploy/nginx.conf" > "$NGINX_CONF"
nginx -t >/dev/null 2>&1 && systemctl reload nginx || { warn "nginx config failed — showing:"; nginx -t; }
ok "nginx reloaded"

# -------- summary --------
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo
echo "=================================================================="
echo " QuantForge deployment complete."
echo "=================================================================="
echo "  install dir   : $INSTALL_DIR"
echo "  python        : $PY_VERSION ($PY_BIN)"
echo "  backend       : http://127.0.0.1:$BACKEND_PORT  (systemd: quantforge.service)"
echo "  public url    : http://$PUBLIC_IP"
echo "  logs          : journalctl -u quantforge.service -f"
echo
echo "  verify: curl http://127.0.0.1:8000/api/system/health"
echo "          curl -o /dev/null -w '%{http_code}\\n' http://127.0.0.1/"
echo "=================================================================="
