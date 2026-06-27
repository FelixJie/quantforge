#!/usr/bin/env bash
# 一键修复「服务器一直让登录」问题。
#
# 根因：代码读环境变量 QF_JWT_SECRET 作为 JWT 签名密钥（auth.py），但旧部署脚本
# 把密钥写成了 SECRET_KEY（名字不匹配）。于是 QF_JWT_SECRET 为空 → 每次启动随机
# 生成临时密钥，且 uvicorn --workers 2 时两个进程各生成不同密钥 → 已签发的 token
# 验签失败 → 前端被反复踢回登录页。
#
# 本脚本：① 给 .env 写入一个固定的 QF_JWT_SECRET（已存在带值则保留，幂等）；
#         ② 清掉用错名字的旧 SECRET_KEY 行；③ 检查 users.json 是否存在；
#         ④ 重启服务并自检。重启后旧 token 会失效一次，请重新登录，之后即稳定。
#
# 用法（服务器上以 root 执行）：  bash /opt/quantforge/deploy/fix_login.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/quantforge}"
ENV_FILE="$APP_DIR/.env"
SERVICE="${SERVICE:-quantforge.service}"

echo "==> 应用目录: $APP_DIR"
[ -f "$ENV_FILE" ] || { echo "!! 找不到 $ENV_FILE，先确认部署路径"; exit 1; }

# ① + ② 写入固定 JWT 密钥
if grep -qE '^QF_JWT_SECRET=.+' "$ENV_FILE"; then
    echo "==> QF_JWT_SECRET 已存在且非空，保留不变（幂等）"
else
    SEC=$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(32))')
    sed -i '/^QF_JWT_SECRET=$/d' "$ENV_FILE"   # 删空值行
    echo "QF_JWT_SECRET=$SEC" >> "$ENV_FILE"
    echo "==> 已写入固定 QF_JWT_SECRET"
fi
# 清掉用错名字的旧密钥行（无害，避免误导）
sed -i '/^SECRET_KEY=/d' "$ENV_FILE" || true
echo "==> 当前密钥行："; grep -n 'QF_JWT_SECRET' "$ENV_FILE" | sed 's/=.*/=<hidden>/'

# ③ 检查账号库
USERS="$APP_DIR/data/users.json"
if [ -f "$USERS" ] && grep -q '"username"' "$USERS" 2>/dev/null; then
    N=$(grep -o '"username"' "$USERS" | wc -l)
    echo "==> users.json 存在，约 $N 个账号"
else
    echo "!! 警告：$USERS 缺失或无账号——这种情况谁都登录不上，需要重新注册账号。"
fi

# ④ 重启 + 自检
echo "==> 重启 $SERVICE ..."
systemctl restart "$SERVICE"
sleep 2
systemctl is-active "$SERVICE" && echo "==> 服务已运行" || { echo "!! 服务未起来，看 journalctl -u $SERVICE -n 50"; exit 1; }

echo "==> 后端健康检查："
curl -s http://127.0.0.1:8000/api/system/health || true
echo
echo "==> 完成。请让用户重新登录一次（本次重启会使旧 token 失效），之后即稳定 7 天、重启不掉线。"
