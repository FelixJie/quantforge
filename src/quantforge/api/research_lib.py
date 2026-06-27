"""研报 PDF 本地库 — 下载东财研报 PDF、抽取正文、建立索引。

供产业链关键词分析的「AI 精读」与前端「研报库」查看复用。
- PDF:   data/cache/research_pdfs/{infoCode}.pdf
- 正文:  data/cache/research_pdfs/{infoCode}.txt   (抽取缓存)
- 索引:  data/cache/research_pdfs/_index.json

东财对行业研报的 infoCode 做了 JS 反爬：候选 URL 返回 HTTP 200 但内容
是 ``<script>...</script>``，不是真正的 PDF。对这种请求我们视为失败，
并在本地写 ``.miss`` 标记文件以避免反复请求。当 PDF 不可用时，模块
暴露 ``fallback_meta_text(report)`` 把标题/机构/日期/行业拼成一段最小
可用文本，交给后续 AI 做主题聚合 —— 这样即使全量 277 篇都下载不到，
也不会让分析任务出现空样本或抛出 500。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import requests
from loguru import logger

# dfcfw.com (东财 PDF CDN) 套了 EdgeOne 机器人防护，会按 TLS 指纹(JA3)拦截
# Python/urllib3 的请求并返回 200 + <script> 反爬页；而系统自带的 curl.exe
# 握手指纹被放行，可稳定拿到真 PDF。故 PDF 下载优先走 curl，requests 兜底。
_CURL = shutil.which("curl") or shutil.which("curl.exe")

UA_CHROME = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 东财多个 PDF 源 — 按优先级依次尝试。行业研报通常不在 dfcfw 上，而是
# 在 data.eastmoney.com 下的 report/noticenews 路径，这里列多种候选。
PDF_CANDIDATES: list[str] = [
    "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
    "https://pdf.dfcfw.com/pdf/H2_{info_code}_1.pdf",
    "https://pdf.dfcfw.com/pdf/H_{info_code}_1.pdf",
    "https://data.eastmoney.com/report/{info_code}.pdf",
    "https://data.eastmoney.com/noticenews/{info_code}.pdf",
]

_LIB_DIR = Path("data/cache/research_pdfs")
_INDEX_PATH = _LIB_DIR / "_index.json"
_MAX_TEXT_CHARS = 6000  # 单篇抽取正文截断上限
_MISS_DAYS = 14         # 同一 infoCode 失败后 N 天内不再重下


def _load_index() -> dict:
    if _INDEX_PATH.exists():
        try:
            return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_index(index: dict) -> None:
    try:
        _LIB_DIR.mkdir(parents=True, exist_ok=True)
        _INDEX_PATH.write_text(
            json.dumps(index, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"research_lib index save failed: {e}")


def _pdf_path(info_code: str) -> Path:
    return _LIB_DIR / f"{info_code}.pdf"


def _txt_path(info_code: str) -> Path:
    return _LIB_DIR / f"{info_code}.txt"


def _looks_like_pdf(content: bytes) -> bool:
    if not content:
        return False
    head = content[:8]
    # 正常 PDF 以 %PDF 开头；以 ``<!DOCTYPE`` 或 ``<script>`` 开头的 200 基本都是反爬页
    if head[:4] == b"%PDF":
        return True
    if b"<script" in head.lower() or head.lstrip().startswith(b"<!"):
        return False
    return False


def _write_miss(info_code: str, note: str = "miss") -> None:
    try:
        _LIB_DIR.mkdir(parents=True, exist_ok=True)
        (_pdf_path(info_code).with_suffix(".miss")).write_text(
            f"{note}\n{datetime.now().isoformat(timespec='seconds')}",
            encoding="utf-8",
        )
    except Exception:
        pass


def _is_miss_fresh(info_code: str) -> bool:
    """若最近 N 天内已标过 miss，则视为不可用，不必重下。"""
    sentinel = _pdf_path(info_code).with_suffix(".miss")
    if not sentinel.exists():
        return False
    try:
        age_days = (datetime.now().timestamp() - sentinel.stat().st_mtime) / 86400.0
        return age_days < _MISS_DAYS
    except Exception:
        return False


def _curl_pdf(url: str, dest: Path) -> bool:
    """用系统 curl.exe 下载 PDF 到 dest（绕开 EdgeOne 对 Python TLS 指纹的拦截）。

    下载后校验 ``%PDF`` 头与大小；非 PDF（反爬页/空文件）则删除并返回 False。
    """
    if not _CURL:
        return False
    tmp = dest.with_suffix(".part")
    try:
        proc = subprocess.run(
            [_CURL, "-s", "-L", "--max-time", "40",
             "-A", UA_CHROME,
             "-e", "https://data.eastmoney.com/",
             "-H", "Accept: application/pdf,*/*;q=0.9",
             "-o", str(tmp), url],
            capture_output=True, timeout=50,
        )
        if proc.returncode != 0 or not tmp.exists():
            return False
        with open(tmp, "rb") as f:
            head = f.read(8)
        if head[:4] != b"%PDF" or tmp.stat().st_size < 1024:
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(dest)
        return True
    except Exception as e:
        logger.debug(f"curl PDF failed {url[:50]}: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def download_pdf(info_code: str) -> Path | None:
    """下载研报 PDF；本地已有 PDF 即直接返回。失败返回 None。

    对以下情况统一视为失败并写 ``.miss`` 标记：
    - HTTP != 200
    - 响应为空或不以 ``%PDF`` 开头（东财反爬页返回 200 + <script>）
    - content-type 不是 pdf（少数站点返回 html/text）
    - 响应体小于 1 KB（假命中）
    """
    if not info_code:
        return None
    path = _pdf_path(info_code)
    # 已有有效 PDF —— 直接命中缓存
    if path.exists() and path.stat().st_size > 1024:
        return path
    # 近期失败过 —— 直接跳过，不再打网络
    if _is_miss_fresh(info_code):
        return None
    try:
        _LIB_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # ① 优先 curl.exe（TLS 指纹被 EdgeOne 放行，成功率高）
    for tpl in PDF_CANDIDATES:
        url = tpl.format(info_code=info_code)
        if _curl_pdf(url, path):
            return path

    # ② 兜底：requests（curl 不可用或全失败时再试）
    session = requests.Session()
    for tpl in PDF_CANDIDATES:
        url = tpl.format(info_code=info_code)
        try:
            r = session.get(
                url,
                headers={
                    "User-Agent": UA_CHROME,
                    "Accept": "application/pdf,*/*;q=0.9",
                    "Referer": "https://data.eastmoney.com/",
                },
                timeout=(10, 20),
                stream=True,
            )
            if r.status_code != 200:
                logger.debug(f"PDF {info_code} {url[:70]} status={r.status_code}")
                continue
            content = r.content
            # 反爬页：200 但内容是 <script>…，直接丢弃（这种最常见）
            if not _looks_like_pdf(content):
                logger.debug(
                    f"PDF {info_code} not pdf, head={bytes(content[:16])!r} ({url[:70]})"
                )
                continue
            if len(content) < 1024:
                logger.debug(f"PDF {info_code} suspicious small ({len(content)} bytes)")
                continue
            path.write_bytes(content)
            return path
        except Exception as e:
            logger.debug(f"PDF download failed {info_code} {url[:40]}: {e}")

    # 所有候选 URL 都失败；写一个 miss 标记，未来 N 天内不再尝试
    _write_miss(info_code, note="all_candidates_failed")
    return None


def _extract_pdf_text(path: Path) -> str:
    """优先 fitz(PyMuPDF)，回退 pdfplumber。失败返回空串。"""
    text = ""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(path)
        parts: list[str] = []
        for page in doc:
            try:
                parts.append(page.get_text())
            except Exception:
                continue
            if sum(len(p) for p in parts) > _MAX_TEXT_CHARS * 2:
                break
        doc.close()
        text = "\n".join(parts)
    except Exception as e:
        logger.debug(f"fitz extract failed, fallback pdfplumber: {e}")
        try:
            import pdfplumber
            parts = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    parts.append(page.extract_text() or "")
                    if sum(len(p) for p in parts) > _MAX_TEXT_CHARS * 2:
                        break
            text = "\n".join(parts)
        except Exception as e2:
            logger.debug(f"pdfplumber extract failed: {e2}")
    return (text or "").strip()


def extract_text(info_code: str) -> str:
    """抽取研报正文（带 .txt 缓存）。需先 download_pdf 成功。

    对"PDF 成功但不可抽取"的情况，也写一个空 .txt 作为标记，
    避免每次分析都重新走一次 fitz/pdfplumber 失败流程。
    """
    if not info_code:
        return ""
    txt = _txt_path(info_code)
    if txt.exists():
        try:
            return txt.read_text(encoding="utf-8")
        except Exception:
            pass
    pdf = _pdf_path(info_code)
    if not pdf.exists():
        return ""
    text = _extract_pdf_text(pdf)[:_MAX_TEXT_CHARS]
    try:
        txt.write_text(text, encoding="utf-8")
    except Exception:
        pass
    return text


def fallback_meta_text(report: dict) -> str:
    """当 PDF 不可用时，用研报元数据拼出一段可用于 AI 主题聚合的摘要。

    返回形如：
        【机构】XX证券
        【行业】光伏设备
        【发布日期】2026-01-20
        【标题】N 型 TOPCon 电池量产经济性持续验证
        （原文正文未能获取，以上信息用于主题/趋势判断参考。）
    """
    if not report:
        return ""
    title = str(report.get("title") or "").strip()
    org = str(report.get("orgSName") or report.get("orgName") or report.get("org") or "").strip()
    date = str(report.get("publishDate") or report.get("date") or "")[:10].strip()
    industry = str(report.get("industryName") or report.get("industry") or "").strip()
    author = str(report.get("researcher") or report.get("author") or "").strip()
    parts: list[str] = []
    if org:
        parts.append(f"【机构】{org}")
    if author:
        parts.append(f"【分析师】{author}")
    if industry:
        parts.append(f"【行业】{industry}")
    if date:
        parts.append(f"【发布日期】{date}")
    if title:
        parts.append(f"【标题】{title}")
    parts.append("（原文正文未能获取，以上信息用于主题/趋势判断参考。）")
    return "\n".join(parts)


def download_and_extract_many(reports: list[dict], cap: int = 0, workers: int = 16,
                              progress_cb=None, text_cap: int = 0,
                              db_flush_every: int = 500) -> dict:
    """批量**并行**下载 + 抽取研报正文。

    即使 PDF 下载失败，也会在 ``texts`` 中放入 ``fallback_meta_text`` 的
    伪正文，保证调用方拿到的样本数不会锐减到 0 引发后续 500。

    内存防护（上万篇研报时单进程被 OOM 杀过）：
    - ``text_cap`` > 0：返回的 ``texts`` 只保留每篇前 ``text_cap`` 字（MAP 只用前
      2800 字），全文仍完整写入 .txt 缓存与 DB，不丢数据。仅截断**返回给内存**的副本。
    - ``db_flush_every``：每累积这么多行就 upsert 落库并清空缓冲，避免上万篇全文
      （含正文）在 ``db_rows`` 里堆到几百 MB。
    """
    from concurrent.futures import ThreadPoolExecutor

    index = _load_index()
    items = reports if not cap or cap <= 0 else reports[:cap]
    total = len(items)
    texts: dict[str, str] = {}
    db_rows: list[dict] = []
    downloaded = extracted = failed = saved = 0

    def _flush_rows(force: bool = False) -> None:
        nonlocal db_rows, saved
        if not db_rows or (not force and len(db_rows) < db_flush_every):
            return
        try:
            from quantforge.data.storage import db_cache
            saved += db_cache.research_pdf_upsert_many(db_rows)
        except Exception as e:
            logger.warning(f"research_pdfs DB save failed: {e}")
        db_rows = []

    def work(r: dict):
        info_code = str(r.get("infoCode") or r.get("info_code") or "").strip()
        if not info_code:
            return None
        ok = download_pdf(info_code) is not None
        text = extract_text(info_code) if ok else ""
        # PDF 失败时写入"标题模式"的伪正文，保证 AI 侧仍有样本
        if not text:
            text = fallback_meta_text(r)
        return (info_code, ok, text, r)

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for res in ex.map(work, items):
            done += 1
            if progress_cb and (done % 20 == 0 or done == total):
                try:
                    progress_cb(done, total)
                except Exception:
                    pass
            if not res:
                continue
            info_code, ok, text, r = res
            if not ok:
                failed += 1
            else:
                downloaded += 1
            if text:
                # 返回给内存的副本截断到 text_cap（全文仍进 .txt/DB）；MAP 只用前 2800 字。
                texts[info_code] = text[:text_cap] if (text_cap and len(text) > text_cap) else text
                extracted += 1
            now = datetime.now().isoformat()
            code = r.get("stockCode", "") or r.get("code", "")
            index[info_code] = {
                "title": r.get("title", ""),
                "org": r.get("orgSName", "") or r.get("org", ""),
                "date": (r.get("publishDate", "") or "")[:10],
                "code": code,
                "chars": len(text),
                "has_pdf": ok,
                "downloaded_at": now,
            }
            db_rows.append({
                "info_code": info_code,
                "code": code,
                "title": r.get("title", ""),
                "org": r.get("orgSName", "") or r.get("org", ""),
                "publish_date": (r.get("publishDate", "") or "")[:10],
                "chars": len(text),
                "text": text,
                "has_pdf": ok,
                "downloaded_at": now,
            })
            _flush_rows()  # 满 db_flush_every 即落库清缓冲，控住内存峰值

    _save_index(index)
    _flush_rows(force=True)  # 落库剩余行
    logger.info(
        f"research_lib: total={total} downloaded={downloaded} "
        f"extracted={extracted} failed={failed} db_saved={saved}"
    )
    return {"texts": texts, "downloaded": downloaded, "extracted": extracted,
            "failed": failed, "total": total, "db_saved": saved}


def get_text(info_code: str) -> str:
    """读取库内已抽取的正文（前端「查看精读」用）：DB 优先 → 本地 .txt → 现抽取。"""
    try:
        from quantforge.data.storage import db_cache
        t = db_cache.research_pdf_get_text(info_code)
        if t:
            return t
    except Exception:
        pass
    txt = _txt_path(info_code)
    if txt.exists():
        try:
            return txt.read_text(encoding="utf-8")
        except Exception:
            pass
    return extract_text(info_code)


def fetch_text(info_code: str) -> str:
    """按需获取单篇研报正文：库内/本地无 → 现下载东财 PDF + 抽取，成功后落库。

    供前端个股详情页点开研报时调用（这些研报通常没被产业链精读批量预下载过）。
    下载失败（反爬/无 PDF）则返回空串，由前端回退到「打开 PDF 原文」外链。
    """
    info_code = (info_code or "").strip()
    if not info_code:
        return ""
    # 已有缓存直接返回
    cached = get_text(info_code)
    if cached:
        return cached
    if download_pdf(info_code) is None:
        return ""
    text = extract_text(info_code)
    if text:
        try:
            from quantforge.data.storage import db_cache
            db_cache.research_pdf_upsert_many([{
                "info_code": info_code,
                "code": "",
                "title": "",
                "org": "",
                "publish_date": "",
                "chars": len(text),
                "text": text,
                "has_pdf": True,
                "downloaded_at": datetime.now().isoformat(),
            }])
        except Exception as e:
            logger.debug(f"fetch_text DB save {info_code} failed: {e}")
    return text
