# -*- coding: utf-8 -*-
"""
扫码登录 -> 自动获取并保存 token (Playwright)

运行后会弹出一个浏览器窗口, 用微信扫码登录 pc.fenchuan8.com,
登录成功后脚本自动读取 fc-token Cookie 写入 token.txt, 并验证有效性, 然后关闭浏览器。

用法:
    python login.py
"""
import json
import os
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, "token.txt")
LOGIN_URL = "https://pc.fenchuan8.com/#/index?forum=" + os.environ.get("FC_QZ_ID", "105371")
WAIT_SECONDS = int(os.environ.get("FC_LOGIN_WAIT", "240"))


def _extract_token(cookie_value):
    """从 fc-token cookie 值里解析出 JWT token; 解析不出返回 None。"""
    if not cookie_value:
        return None
    for s in (urllib.parse.unquote(cookie_value), cookie_value):
        s = s.strip()
        if s.startswith("{"):
            try:
                obj = json.loads(s)
                if isinstance(obj, dict) and obj.get("token"):
                    return str(obj["token"])
            except Exception:
                pass
    return None


def _validate(token):
    """用 token 调一次接口确认登录态有效。"""
    try:
        import server
        resp = server.api_post("sx/newindex/cinfo",
                               {"qz_id": server.QZ_ID, "page": 1}, token)
        data = resp.get("data")
        inner = data.get("code") if isinstance(data, dict) else None
        return not (resp.get("code") in (900, 401) or inner == 22222)
    except Exception as e:
        print("  (验证时出错, 先按成功处理:", e, ")")
        return True


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 playwright, 请先运行: python -m pip install playwright "
              "&& python -m playwright install chromium")
        sys.exit(1)

    print("正在打开浏览器, 请用微信扫码登录...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = browser.new_context(no_viewport=True)
        page = ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print(f"请在 {WAIT_SECONDS} 秒内完成扫码登录 (登录成功会自动捕获 token)...")
        token = None
        deadline = time.time() + WAIT_SECONDS
        while time.time() < deadline:
            try:
                cookies = ctx.cookies()
            except Exception:
                cookies = []
            for c in cookies:
                if c.get("name") == "fc-token":
                    t = _extract_token(c.get("value"))
                    if t and _validate(t):
                        token = c.get("value")
                        break
            if token:
                break
            time.sleep(1.5)

        browser.close()

    if not token:
        print("× 超时未检测到有效登录, 未保存。请重试 python login.py")
        sys.exit(2)

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token)
    print("√ 登录成功, token 已写入 token.txt")
    print("  抓取服务会在下次刷新时自动使用新 token (或在页面点'立即刷新')。")


if __name__ == "__main__":
    main()
