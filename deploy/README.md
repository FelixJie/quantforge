# QuantForge 服务器部署手册（百度云 BCC · CentOS / Rocky / RHEL）
#
# 目标：
#   - 后端：FastAPI + uvicorn，systemd 托管，监听 127.0.0.1:8000
#   - 前端：Vue3 + Vite 打包产物，由 Nginx 代理，对外 80 端口
#   - 数据库：SQLite（项目默认）
#
# 在百度云 BCC 控制台「远程连接」里以 root 身份执行下列命令即可。
# ---------------------------------------------------------------

# 0) 以 root 登录后，先确认发行版
cat /etc/redhat-release   # 例如 CentOS Linux release 7.x / 8.x 或 Rocky Linux 9.x

# ---------------------------------------------------------------
# 方式 A（推荐）：一键脚本
# ---------------------------------------------------------------
# 把整个 stock_trade 项目目录（含 deploy/）上传到 /opt/quantforge 后：
#
#   sudo bash /opt/quantforge/deploy/deploy_centos.sh
#
# 之后更新代码：
#
#   sudo bash /opt/quantforge/deploy/deploy_centos.sh --update
#
# 下面是方式 B（手动，分步）的完整命令清单。
# ---------------------------------------------------------------

# 1) 安装基础包 & EPEL / Remi 仓库（用于装 python3.12）
sudo dnf install -y epel-release curl ca-certificates gnupg2 git
# 如果是 CentOS 7 则用 yum 代替 dnf
OS_VER=$(rpm -E %{rhel})
sudo dnf install -y https://rpms.remirepo.net/enterprise/remi-release-"$OS_VER".rpm
sudo dnf makecache

# 2) 安装 Python 3.12（来自 Remi）
sudo dnf module reset -y python3 2>/dev/null || true
sudo dnf install -y --enablerepo=remi python3.12 python3.12-pip python3.12-devel
python3.12 --version   # 期望 Python 3.12.x

# 3) 安装 Node.js 20（用于 Vite 构建前端）
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo dnf install -y nodejs
node -v   # 期望 v20.x.x
npm  -v

# 4) 安装并启用 Nginx
sudo dnf install -y nginx
sudo systemctl enable --now nginx
# 禁用默认欢迎页，避免端口冲突
sudo mv /etc/nginx/conf.d/welcome.conf /etc/nginx/conf.d/welcome.conf.disabled 2>/dev/null || true

# 5) 防火墙放行 HTTP / HTTPS
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
sudo firewall-cmd --list-services   # 应包含 http https

# 6) SELinux（若为 Enforcing 模式，需允许 Nginx 反代 & 读取 /opt）
if [ "$(getenforce)" = "Enforcing" ]; then
    sudo setsebool -P httpd_can_network_connect 1
    sudo setsebool -P httpd_can_network_relay   1
fi

# 7) 放置代码（任选一种）
# --- 方式 A：从 git 拉取 ---
#   sudo git clone --branch main --depth 1 https://github.com/你的账号/你的仓库.git /opt/quantforge
#
# --- 方式 B：从本地 scp 上传 ---
#   （本地） scp -r ./stock_trade root@服务器IP:/tmp/
#   （服务器） sudo mv /tmp/stock_trade /opt/quantforge

sudo mkdir -p /opt/quantforge
# 把代码放进去后：
sudo chown -R nginx:nginx /opt/quantforge
sudo mkdir -p /opt/quantforge/data /opt/quantforge/data/parquet /opt/quantforge/data/cache /opt/quantforge/logs

# 8) Python 虚拟环境与依赖
python3.12 -m venv /opt/quantforge/.venv
/opt/quantforge/.venv/bin/pip install --upgrade pip setuptools wheel
/opt/quantforge/.venv/bin/pip install -e /opt/quantforge[api]
/opt/quantforge/.venv/bin/pip install uvicorn

# 9) 构建前端
cd /opt/quantforge/web
npm install --no-audit --no-fund
npm run build

# 10) .env 配置文件
if [ ! -f /opt/quantforge/.env ]; then
    sudo cp /opt/quantforge/.env.example /opt/quantforge/.env
    SECRET=$(/opt/quantforge/.venv/bin/python -c 'import secrets;print(secrets.token_hex(32))')
    echo "" | sudo tee -a /opt/quantforge/.env
    echo "SECRET_KEY=$SECRET" | sudo tee -a /opt/quantforge/.env
fi
sudo chown nginx:nginx /opt/quantforge/.env
sudo chmod 600 /opt/quantforge/.env
# 如需 iFinD / Tushare，编辑 .env 填入对应 token

# 11) systemd 服务（注意把服务用户 www-data 改为 nginx）
sudo sed -e 's|User=www-data|User=nginx|; s|Group=www-data|Group=nginx|' \
    /opt/quantforge/deploy/quantforge.service | sudo tee /etc/systemd/system/quantforge.service
sudo systemctl daemon-reload
sudo systemctl enable  quantforge.service
sudo systemctl restart quantforge.service
sudo systemctl status  quantforge.service
# 查看日志： journalctl -u quantforge.service -f

# 12) Nginx（CentOS 放在 /etc/nginx/conf.d/*.conf）
sudo cp /opt/quantforge/deploy/nginx.conf /etc/nginx/conf.d/quantforge.conf
# SELinux 给静态文件打上可访问标签（若 Enforcing）
if [ "$(getenforce)" = "Enforcing" ]; then
    sudo semanage fcontext -a -t httpd_sys_content_t "/opt/quantforge/web/dist(/.*)?" 2>/dev/null || true
    sudo restorecon -R /opt/quantforge/web/dist
fi
sudo nginx -t && sudo systemctl reload nginx

# 13) 验证
curl -s http://127.0.0.1:8000/api/system/health   # 后端健康检查
curl -s http://127.0.0.1/                          # 首页
PUBLIC_IP=$(hostname -I | awk '{print $1}')
echo "在浏览器访问： http://$PUBLIC_IP"

# ---------------------------------------------------------------
# 常见问题排查
# ---------------------------------------------------------------
# - 后端无法启动 → journalctl -u quantforge.service -n 50
# - 502 Bad Gateway  → uvicorn 没起来，检查 service / 端口 8000
# - 403 Forbidden    → SELinux 问题：setsebool -P httpd_can_network_connect 1
# - 浏览器无法访问   → 百度云 BCC 安全组未放行 TCP:80（或 firewalld 未允许）
# - Python 模块缺失 → /opt/quantforge/.venv/bin/pip install -e /opt/quantforge[api]

# ---------------------------------------------------------------
# 后续维护
# ---------------------------------------------------------------
# 重启服务：
#   sudo systemctl restart quantforge.service
# 拉取最新代码并重建：
#   sudo bash /opt/quantforge/deploy/deploy_centos.sh --update
# 查看实时日志：
#   sudo journalctl -u quantforge.service -f
# 升级依赖：
#   /opt/quantforge/.venv/bin/pip install --upgrade -e /opt/quantforge[api]
#   cd /opt/quantforge/web && npm install && npm run build

# ---------------------------------------------------------------
# 百度云 BCC 安全组
# ---------------------------------------------------------------
# 记得在百度云控制台给实例绑定的安全组放行 TCP:80（以及 443 若后续启用 HTTPS）。
#
# 如需启用 HTTPS，建议用 certbot：
#   sudo dnf install -y certbot python3-certbot-nginx
#   sudo certbot --nginx -d your.domain.com
