# -*- coding: utf-8 -*-
"""
纷传 (fenchuan8) 博主圈子 最新博客抓取 + 展示 小应用 (纯标准库, 无需 pip 安装)

- 每 10 分钟抓取一次指定圈子 (qz_id) 的最新帖子, 缓存到 cache.json
- 提供网页 / 与接口 /api/posts 供前端展示
- 需要登录态: 把浏览器里 pc.fenchuan8.com 的 fc-token Cookie 值粘进 token.txt

用法:
    python server.py
然后浏览器打开 http://127.0.0.1:8770
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------- 配置
HERE = os.path.dirname(os.path.abspath(__file__))
API_BASE = "https://api.leadshiptech.com/"
SIGN_SECRET = "AS28@~#*shFG486shfksdfSDF@#%dsdf"  # 来自前端 app.js 的签名盐
QZ_ID = os.environ.get("FC_QZ_ID", "105371")       # 圈子/博主 id (URL 里的 forum=)
PORT = int(os.environ.get("FC_PORT", "8770"))
INTERVAL = int(os.environ.get("FC_INTERVAL", "600"))  # 抓取间隔, 秒 (默认 10 分钟)
NOTIFY = os.environ.get("FC_NOTIFY", "1") != "0"      # 有新帖时弹 Windows 桌面通知
TOKEN_FILE = os.path.join(HERE, "token.txt")
CACHE_FILE = os.path.join(HERE, "cache.json")
INDEX_FILE = os.path.join(HERE, "index.html")

# ---------------------------------------------------------------- 共享状态
_lock = threading.Lock()
STATE = {
    "status": "init",       # ok | login_required | error | init
    "updated_at": 0,
    "error": "",
    "qz_id": QZ_ID,
    "posts": [],
    "max_id": 0,             # 已知最新帖子的 id, 用于检测新帖
    "raw_sample": None,      # 调试用: 第一条原始记录
}


# ---------------------------------------------------------------- 桌面通知
def notify_windows(title, message):
    """Windows 10/11 桌面 Toast 通知 (best-effort, 失败不影响主流程)。"""
    if not NOTIFY or os.name != "nt":
        return
    ps = (
        "$ErrorActionPreference='Stop';"
        "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$x=$t.GetElementsByTagName('text');"
        "$x.Item(0).AppendChild($t.CreateTextNode($env:FC_NT))|Out-Null;"
        "$x.Item(1).AppendChild($t.CreateTextNode($env:FC_NM))|Out-Null;"
        "$toast=[Windows.UI.Notifications.ToastNotification]::new($t);"
        "$app='{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)"
    )
    env = dict(os.environ, FC_NT=str(title), FC_NM=str(message))
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        print("notify error:", e)


# ---------------------------------------------------------------- token
def read_token():
    """读取 token.txt; 兼容直接粘贴 fc-token 的 JSON 串或裸 token。"""
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except FileNotFoundError:
        return ""
    if not raw:
        return ""
    # fc-token 通常是被 URL/JSON 编码的对象, 形如 {"token":"xxx",...}
    txt = raw
    try:
        txt = urllib.parse.unquote(raw)
    except Exception:
        pass
    for candidate in (txt, raw):
        s = candidate.strip()
        if s.startswith("{"):
            try:
                obj = json.loads(s)
                if isinstance(obj, dict) and obj.get("token"):
                    return str(obj["token"])
            except Exception:
                pass
    return raw


# ---------------------------------------------------------------- 签名请求
def api_post(path, params, token):
    ts = int(time.time())
    data = dict(params)
    data["_"] = ts
    data["app_name"] = "sx"
    data["task_token"] = token or "empty1"
    # 与前端一致: sign = md5(secret + 未编码的 querystring)
    qs = "&".join(f"{k}={v}" for k, v in data.items())
    data["sign"] = hashlib.md5((SIGN_SECRET + qs).encode("utf-8")).hexdigest()
    data["apiversion"] = "2.3"
    data["clientfrom"] = "pc"
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        API_BASE + path.lstrip("/"),
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://pc.fenchuan8.com",
            "Referer": "https://pc.fenchuan8.com/",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# ---------------------------------------------------------------- 解析
import html
import re

_NAV_RE = re.compile(
    r'<navigator\b[^>]*?\bhref="([^"]*)"[^>]*>(.*?)</navigator>',
    re.I | re.S)
_NAV_NOHREF_RE = re.compile(r'<navigator\b[^>]*>(.*?)</navigator>', re.I | re.S)
_TAG_RE = re.compile(r'<[^>]+>')


def clean_content(raw):
    """把帖子正文里的小程序 <navigator> 标签转成纯文本, 并抽出其中的外链。"""
    if not raw:
        return "", []
    links = []

    def _nav(m):
        href = html.unescape(m.group(1) or "").strip()
        text = _TAG_RE.sub("", m.group(2) or "").strip()
        if href:
            links.append({"text": text or href, "url": href})
        return text

    s = _NAV_RE.sub(_nav, raw)
    s = _NAV_NOHREF_RE.sub(lambda m: _TAG_RE.sub("", m.group(1) or ""), s)
    s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    return s.strip(), links


def _normalize_one(it):
    if not isinstance(it, dict):
        return None
    images = []
    for m in (it.get("media_list") or []):
        if isinstance(m, dict):
            u = m.get("min_img") or m.get("url")
            full = m.get("url") or m.get("min_img")
            if u:
                images.append({"thumb": u, "full": full})
    text, links = clean_content(it.get("content") or "")
    if not text:
        text = (it.get("summary") or "").strip()
    return {
        "id": str(it.get("id", "")),
        "title": str(it.get("title") or "").strip(),
        "text": text,
        "links": links,
        "author": str(it.get("username") or "").strip(),
        "avatar": str(it.get("avatar") or "").strip(),
        "time": str(it.get("fbtime") or it.get("create_time") or "").strip(),
        "images": images,
        "url": str(it.get("h5_url") or "").strip(),
        "is_top": bool(it.get("show_top") or it.get("is_top")),
        "stats": {
            "zan": it.get("zan_num", 0),
            "comment": it.get("comment_num", 0),
            "view": it.get("view_num", 0),
        },
    }


def normalize(api_data):
    rows = []
    if isinstance(api_data, dict):
        lst = api_data.get("list")
        if isinstance(lst, dict):
            rows = lst.get("data") or []
        elif isinstance(lst, list):
            rows = lst
    out = []
    for it in rows:
        n = _normalize_one(it)
        if n:
            out.append(n)
    # 置顶优先, 其余按时间倒序(接口本身已大致有序, 这里稳妥再排一次)
    out.sort(key=lambda p: (not p["is_top"], ), )
    return out, (rows[0] if rows else None)


# ---------------------------------------------------------------- 抓取
def _set_login_required(error):
    """设为需要登录, 并在状态从其它态切换过来时弹一次桌面通知。"""
    with _lock:
        was = STATE.get("status")
        STATE.update(status="login_required", error=error)
    if was != "login_required":
        notify_windows("登录已过期", "请扫码重新登录 (运行 login.py 或点页面上的'重新登录')")


def fetch_once():
    token = read_token()
    if not token:
        _set_login_required("token.txt 为空, 请扫码登录")
        return
    try:
        resp = api_post("sx/newindex/cinfo", {"qz_id": QZ_ID, "page": 1}, token)
    except Exception as e:
        with _lock:
            STATE.update(status="error", error=f"请求失败: {e}")
        return
    code = resp.get("code")
    data = resp.get("data")
    inner_code = data.get("code") if isinstance(data, dict) else None
    # 未登录/登录失效: 顶层 900, 或 cinfo 返回 data.code==22222
    if code in (900, 401) or inner_code == 22222:
        _set_login_required(f"登录态失效 (code={code}/{inner_code}, {resp.get('msg')}), 请扫码登录")
        return
    posts, sample = normalize(resp.get("data"))

    # --- 检测新帖 (帖子 id 自增, id 越大越新) ---
    def _idnum(p):
        try:
            return int(p.get("id") or 0)
        except (TypeError, ValueError):
            return 0
    cur_max = max((_idnum(p) for p in posts), default=0)
    with _lock:
        prev_max = STATE.get("max_id", 0)
        STATE.update(status="ok", error="", updated_at=int(time.time()),
                     posts=posts, raw_sample=sample,
                     max_id=max(prev_max, cur_max))
    new_posts = [p for p in posts if _idnum(p) > prev_max]
    save_cache()
    print(f"[{time.strftime('%H:%M:%S')}] 抓取成功, {len(posts)} 条"
          + (f", 其中新帖 {len(new_posts)} 条" if prev_max and new_posts else ""))

    # 首次运行 (prev_max==0) 只建立基线, 不打扰; 之后有新帖才通知
    if prev_max and new_posts:
        newest = max(new_posts, key=_idnum)
        preview = (newest.get("text") or newest.get("title") or "").strip()
        preview = preview.replace("\n", " ")[:60] or "（图片/无文字）"
        author = newest.get("author") or "博主"
        title = (f"{author} 发了 {len(new_posts)} 条新帖"
                 if len(new_posts) > 1 else f"{author} 发了新帖")
        notify_windows(title, preview)


def save_cache():
    try:
        with _lock:
            snap = dict(STATE)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("save_cache error:", e)


def load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            snap = json.load(f)
        with _lock:
            STATE.update(snap)
        print("已载入上次缓存", len(snap.get("posts", [])), "条")
    except Exception:
        pass


def scheduler():
    while True:
        fetch_once()
        time.sleep(INTERVAL)


# ---------------------------------------------------------------- 扫码登录
_login_proc = None


def launch_login():
    """启动 login.py 弹出浏览器扫码; 登录进程结束后自动刷新一次。"""
    global _login_proc
    if _login_proc is not None and _login_proc.poll() is None:
        return False  # 已有一个登录窗口在进行中
    script = os.path.join(HERE, "login.py")
    try:
        _login_proc = subprocess.Popen([sys.executable, script], cwd=HERE)
    except Exception as e:
        print("launch_login error:", e)
        return False

    def _after():
        try:
            _login_proc.wait()
        except Exception:
            pass
        fetch_once()  # 登录完成后立即用新 token 抓一次

    threading.Thread(target=_after, daemon=True).start()
    return True


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # 静默

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            try:
                with open(INDEX_FILE, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, "index.html not found", "text/plain; charset=utf-8")
        elif path == "/api/posts":
            with _lock:
                snap = dict(STATE)
            snap["interval"] = INTERVAL
            self._send(200, json.dumps(snap, ensure_ascii=False))
        elif path == "/api/refresh":
            threading.Thread(target=fetch_once, daemon=True).start()
            self._send(200, json.dumps({"ok": True}))
        elif path == "/api/login":
            started = launch_login()
            self._send(200, json.dumps({"ok": True, "started": started}))
        else:
            self._send(404, json.dumps({"error": "not found"}))


def main():
    load_cache()
    t = threading.Thread(target=scheduler, daemon=True)
    t.start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"博客抓取服务已启动: http://127.0.0.1:{PORT}")
    print(f"圈子 qz_id={QZ_ID}, 抓取间隔 {INTERVAL}s")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("bye")


if __name__ == "__main__":
    main()
