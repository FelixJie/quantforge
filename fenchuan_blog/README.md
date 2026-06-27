# 纷传博客抓取 (fenchuan_blog)

每 10 分钟抓取指定圈子/博主在 [pc.fenchuan8.com](https://pc.fenchuan8.com) 的最新帖子，并在本地网页展示。纯 Python 标准库实现，无需安装任何依赖。

## 1. 登录拿 token

### 方式一（推荐）：扫码登录，自动保存

```powershell
python login.py
```

会弹出一个浏览器窗口，用**微信扫码**登录，脚本自动抓取 `fc-token` 写入 `token.txt` 并校验有效性，然后关闭浏览器。

> token 过期后（约 7 天），页面顶部会变黄并出现 **「扫码重新登录」** 按钮，点一下就会自动弹出扫码浏览器；过期时还会弹一条桌面通知提醒。也可以随时手动 `python login.py`。
>
> 依赖（已安装）：`python -m pip install playwright && python -m playwright install chromium`

### 方式二：手动粘贴

1. 浏览器登录 https://pc.fenchuan8.com/#/index?forum=105371
2. `F12` → **Application / 应用** → **Cookies** → `https://pc.fenchuan8.com`
3. 找到 **`fc-token`**，复制它的值，粘贴到 `token.txt`（整段粘即可）

## 2. 启动

```powershell
python server.py
```

然后浏览器打开 http://127.0.0.1:8770

## 功能

- **每 10 分钟自动抓取**最新帖子（正文、配图、互动数、置顶、原帖链接）
- **新帖高亮**：页面记住你上次看到的位置，新发布的帖子加红色 `NEW` 标记并高亮；顶部「标为已读」按钮可清除
- **桌面通知**：抓到新帖时弹 Windows 桌面 Toast 通知（浏览器没开也能收到）。首次启动只建立基线、不打扰

## 配置（可选，环境变量）

| 变量 | 默认 | 说明 |
|------|------|------|
| `FC_QZ_ID` | `105371` | 圈子 id（URL 里的 `forum=`） |
| `FC_PORT` | `8770` | 网页端口 |
| `FC_INTERVAL` | `600` | 抓取间隔（秒），默认 10 分钟 |
| `FC_NOTIFY` | `1` | 设为 `0` 关闭桌面通知 |

## 开机自启（已配置）

已注册 Windows 计划任务 **`FenchuanBlogScraper`**：每次登录系统时用 `pythonw.exe` 在后台静默启动（无黑窗口），监听 `http://127.0.0.1:8770`。

常用管理命令（PowerShell）：

```powershell
Start-ScheduledTask  -TaskName FenchuanBlogScraper   # 立即启动
Stop-ScheduledTask   -TaskName FenchuanBlogScraper   # 停止
Get-ScheduledTaskInfo -TaskName FenchuanBlogScraper  # 查看状态
Disable-ScheduledTask -TaskName FenchuanBlogScraper  # 暂停自启（保留任务）
Unregister-ScheduledTask -TaskName FenchuanBlogScraper -Confirm:$false  # 彻底删除自启
```

> 自启后无控制台窗口，`print` 日志看不到属正常；状态以页面顶部为准。
> 关闭后想重新跑，直接 `Start-ScheduledTask` 或手动 `python server.py` 均可。

## 文件

- `server.py` — 抓取 + 定时器 + 网页服务 + `/api/login` 一键扫码
- `login.py` — 扫码登录脚本（Playwright，自动写 token.txt）
- `index.html` — 展示页面（深色，自动刷新）
- `token.txt` — 你的登录 token
- `cache.json` — 最近一次抓取结果（自动生成）
