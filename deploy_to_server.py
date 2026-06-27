"""Deploy QuantForge to remote CentOS server via SSH.

Usage:
    python deploy_to_server.py

Reads credentials from env or hardcoded below. Does:
    1. SSH connect & show OS info
    2. Upload project (excluding node_modules/.venv/data cache)
    3. Run deploy_centos.sh remotely and stream logs back
"""
from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path

import paramiko

# Credentials come from the environment so no secret is committed. Set them via:
#   PowerShell:  $env:DEPLOY_HOST="..."; $env:DEPLOY_PASSWORD="..."; python deploy_to_server.py
#   bash:        DEPLOY_PASSWORD=... python deploy_to_server.py
HOST = os.environ.get("DEPLOY_HOST", "106.12.146.52")
USER = os.environ.get("DEPLOY_USER", "root")
PASSWORD = os.environ.get("DEPLOY_PASSWORD")
REMOTE_DIR = os.environ.get("DEPLOY_REMOTE_DIR", "/opt/quantforge")
LOCAL_ROOT = Path(__file__).resolve().parent

if not PASSWORD:
    sys.exit(
        "error: set the server password in DEPLOY_PASSWORD env var, e.g.\n"
        "  PowerShell:  $env:DEPLOY_PASSWORD='...'; python deploy_to_server.py"
    )

# Exclude patterns when uploading (paths relative to LOCAL_ROOT).
# Dirs excluded ANYWHERE in the path (build artifacts / vcs / caches):
EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    "dist", ".idea", ".vscode", ".pytest_cache",
}
# Dirs excluded only at the TOP level — must NOT match src/quantforge/data:
EXCLUDE_TOP_DIRS = {"data"}
# Exact relative-path prefixes to exclude (local caches that must never ship).
# web/data/cache holds thousands of downloaded research PDFs — pure local cache,
# the backend reads top-level data/ at runtime, so shipping these only wastes time.
EXCLUDE_PREFIXES = ("web/data/",)
EXCLUDE_SUFFIXES = (".log", ".pyc", ".pyo", ".db", ".db-wal", ".db-shm")


def make_ssh() -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30,
                banner_timeout=30, auth_timeout=30)
    return ssh


def run(ssh, cmd, show=True) -> int:
    """Run a command; stream stdout/stderr line by line."""
    if show:
        print(f"\n$ {cmd}", flush=True)
    chan = ssh.get_transport().open_session()
    chan.set_combine_stderr(True)
    chan.get_pty()
    chan.exec_command(cmd)
    buf = b""
    while True:
        if chan.recv_ready():
            data = chan.recv(4096)
            buf += data
            # Print as text, line buffered
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    sys.stdout.write(line.decode("utf-8", errors="replace") + "\n")
                except Exception:
                    pass
            # Show partial if it ends with a prompt-ish marker
            tail = buf.decode("utf-8", errors="replace")
            if tail.endswith("$ ") or tail.endswith("# "):
                sys.stdout.write(tail)
                sys.stdout.flush()
        if chan.exit_status_ready():
            # drain any remaining
            while chan.recv_ready():
                data = chan.recv(4096)
                try:
                    sys.stdout.write(data.decode("utf-8", errors="replace"))
                except Exception:
                    pass
            break
        sys.stdout.flush()
        time.sleep(0.1)
    status = chan.recv_exit_status()
    sys.stdout.flush()
    return status


def is_excluded(rel: str) -> bool:
    """True if this relative path should be skipped on upload."""
    parts = rel.split("/")
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    if parts[0] in EXCLUDE_TOP_DIRS:
        return True
    if any(rel == p.rstrip("/") or rel.startswith(p) for p in EXCLUDE_PREFIXES):
        return True
    name = parts[-1]
    return any(name.endswith(s) for s in EXCLUDE_SUFFIXES)


def walk_upload(ssh: paramiko.SSHClient, sftp: paramiko.SFTPClient,
                local_root: Path, remote_root: str) -> None:
    """Recursively upload files in local_root to remote_root."""
    remote_root = remote_root.rstrip("/")

    # Create all directories first (skip excluded ones)
    dirs_to_make = set()
    for path in local_root.rglob("*"):
        rel = path.relative_to(local_root).as_posix()
        if is_excluded(rel):
            continue
        if not path.is_dir():
            rel_dir = "/".join(rel.split("/")[:-1])
            if rel_dir:
                dirs_to_make.add(rel_dir)
            continue
        # directory itself
        parts = rel.split("/")
        for i in range(1, len(parts) + 1):
            dirs_to_make.add("/".join(parts[:i]))

    # mkdir -p via ssh (sftp has no recursive mkdir)
    if dirs_to_make:
        dir_list = " ".join(f'"{remote_root}/{d}"' for d in sorted(dirs_to_make))
        run(ssh, f"mkdir -p {dir_list}", show=False)

    # Upload files (respecting excludes)
    count = 0
    for path in sorted(local_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(local_root).as_posix()

        if is_excluded(rel):
            continue

        remote = f"{remote_root}/{rel}"
        try:
            sftp.put(str(path), remote)
        except Exception as e:
            print(f"  !! failed to upload {rel}: {e}", flush=True)
            continue

        if rel.endswith(".sh"):
            try:
                sftp.chmod(remote, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
                           | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
            except Exception:
                pass
        count += 1
        if count % 50 == 0:
            print(f"  uploaded {count} files ...", flush=True)
    print(f"  uploaded {count} files total.", flush=True)


def main() -> int:
    print(f"==> Connecting to {USER}@{HOST} ...", flush=True)
    ssh = make_ssh()
    print("==> Connected. Checking remote OS:", flush=True)
    for cmd in [
        "cat /etc/redhat-release 2>/dev/null || cat /etc/os-release",
        "uname -r",
        "whoami",
        "hostname -I",
    ]:
        run(ssh, cmd)

    # Ensure install dir exists
    run(ssh, f"mkdir -p {REMOTE_DIR}")

    # Always do a FULL re-upload so the server matches the local tree. (An older
    # version skipped upload when pyproject.toml already existed — that silently
    # left the server running stale code. Never skip again.)
    # First wipe server-side code dirs so files deleted locally don't linger,
    # but keep .venv / data / .env which live only on the server.
    print("\n==> Wiping server code dirs (keeping .venv / data / .env) ...", flush=True)
    run(ssh, f"rm -rf {REMOTE_DIR}/src {REMOTE_DIR}/web/src {REMOTE_DIR}/web/dist {REMOTE_DIR}/deploy")

    print("\n==> Uploading project files via SFTP (excluding caches) ...", flush=True)
    sftp = ssh.open_sftp()
    walk_upload(ssh, sftp, LOCAL_ROOT, REMOTE_DIR)
    sftp.close()

    run(ssh, f"chmod +x {REMOTE_DIR}/deploy/deploy_centos.sh")

    print("\n==> Running deploy_centos.sh. Python 3.12 will be built from source ~5-15 min.", flush=True)
    print("    (output is streamed live — be patient during 'make'.)", flush=True)
    print("-" * 72, flush=True)

    status = run(ssh, f"bash {REMOTE_DIR}/deploy/deploy_centos.sh")

    print("-" * 72, flush=True)
    print(f"\n==> deploy script exit status: {status}", flush=True)

    if status == 0:
        print("\n==> Post-deploy verification:", flush=True)
        run(ssh, "systemctl status quantforge.service --no-pager | head -20")
        run(ssh, "curl -sS http://127.0.0.1:8000/api/system/health 2>&1 || echo '(backend not ready)'")
        run(ssh, "curl -sS -o /dev/null -w 'HTTP %{http_code}\\n' http://127.0.0.1/")
        run(ssh, "PUBLIC=$(curl -s ifconfig.me 2>/dev/null || hostname -I|awk '{print $1}'); echo \"public URL: http://$PUBLIC\"; curl -sS -o /dev/null -w 'HTTP %{http_code}\\n' http://$PUBLIC/")
    else:
        print("\n==> Deploy failed. Dumping diagnostics:", flush=True)
        run(ssh, "journalctl -u quantforge.service -n 60 --no-pager 2>/dev/null || echo '(no journal)'")
        run(ssh, "ls -la /opt/quantforge/web/dist/ 2>/dev/null | head -20")
        run(ssh, "ls -la /opt/quantforge/.venv/bin/ 2>/dev/null | head")

    ssh.close()
    return status


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[interrupted]", flush=True)
        sys.exit(130)
    except Exception as exc:
        print(f"\n[error] {exc}", flush=True, file=sys.stderr)
        sys.exit(2)
