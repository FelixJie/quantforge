"""Deep diagnosis of server issues."""
from __future__ import annotations
import os, sys, time
import paramiko

HOST = os.environ.get("DEPLOY_HOST", "106.12.146.52")
USER = os.environ.get("DEPLOY_USER", "root")
PASSWORD = os.environ.get("DEPLOY_PASSWORD")

if not PASSWORD:
    sys.exit("Set DEPLOY_PASSWORD env var")

def make_ssh():
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30,
                banner_timeout=30, auth_timeout=30)
    return ssh

def run(ssh, cmd):
    print(f"\n$ {cmd}", flush=True)
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if out:
        print(out, flush=True)
    if err:
        print(f"[stderr] {err}", flush=True)
    return out

def main():
    print(f"==> Connecting to {USER}@{HOST} ...", flush=True)
    ssh = make_ssh()

    # 1. Check frontend index.html
    run(ssh, "cat /opt/quantforge/web/dist/index.html")

    # 2. Check assets
    run(ssh, "ls -la /opt/quantforge/web/dist/assets/")

    # 3. Check nginx config
    run(ssh, "cat /etc/nginx/conf.d/quantforge.conf")

    # 4. Check service restart count and recent crashes
    run(ssh, "systemctl show quantforge.service -p NRestarts,ActiveEnterTimestamp,ExecMainStartTimestamp")

    # 5. Check memory and CPU
    run(ssh, "free -h")
    run(ssh, "ps aux --sort=-%mem | head -10")

    # 6. Check journalctl for errors/crashes in last hour
    run(ssh, "journalctl -u quantforge.service --since '1 hour ago' --no-pager | grep -iE 'error|crash|kill|signal|traceback|exception|fail' | tail -30")

    # 7. Check if workers are actually responding
    run(ssh, "curl -sS -w '\\nHTTP %{http_code} Time: %{time_total}s\\n' http://127.0.0.1:8000/api/system/health")
    run(ssh, "curl -sS -w '\\nHTTP %{http_code} Time: %{time_total}s\\n' http://127.0.0.1:8000/api/market/overview 2>&1 | head -5")
    run(ssh, "curl -sS -w '\\nHTTP %{http_code} Time: %{time_total}s\\n' http://127.0.0.1:8000/api/news/flash?count=12 2>&1 | head -5")

    # 8. Check .env content (mask secrets)
    run(ssh, "cat /opt/quantforge/.env | sed 's/=.*/=***/'")

    # 9. Check disk space
    run(ssh, "df -h /opt")

    ssh.close()

if __name__ == "__main__":
    main()
