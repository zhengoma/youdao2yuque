#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片本地化：把 youdaonote/ 下所有 md 引用的「远程图片」下载到 md 同级 images/
目录，并把 md 里的链接改成本地相对路径，方便整体打包后导入语雀显示。

处理规则：
    - ![alt](http(s)://...)    -> 下载到 <md 同级>/images/，链接改为 images/<hash>.<ext>
    - ![alt](data:...)         -> 保留（base64 内联图，无需下载）
    - ![alt](/storage/...)     -> 保留（安卓本地路径，原文件已丢失）
    - ![alt](images/xxx)       -> 保留（已经本地化）

每个 URL 全局只下载一次（按 URL md5 缓存到内存），同一 URL 在多个 md 中引用时
会分别写文件到各自的 images/ 下，导入语雀时不依赖跨目录相对路径。

失败的 URL 会保留原链接并记录到 image-download-failures.log。

用法：
    python3 localize_images.py --dry-run            # 先看一遍计划
    python3 localize_images.py                       # 真正下载
    python3 localize_images.py --concurrency 4       # 调整并发
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

# ================= 配置 =================
# 默认扫描目录；运行时可用 --root 覆盖
ROOT = Path("./youdaonote").resolve()
FAIL_LOG = Path("./image-download-failures.log").resolve()
COOKIES_PATH = Path("./cookies.json").resolve()

DOWNLOAD_TIMEOUT = 15
DOWNLOAD_RETRIES = 2  # 总尝试次数 = RETRIES + 1
MAX_IMG_BYTES = 20 * 1024 * 1024  # 单图最大 20MB，避免被异常大资源拖死
# ========================================

IMG_RE = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
# 更宽松的"任何 ![](...) 直到下一个 ')'"，用于清理含空格的脏 URL
LOOSE_IMG_RE = re.compile(r'!\[[^\]]*\]\([^)]*\)')

SKIP_PREFIXES = ('data:', '/storage/', './', '../')

DEFAULT_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0 Safari/537.36'
    ),
    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
}

REFERER_MAP = {
    'mmbiz.qpic.cn': 'https://mp.weixin.qq.com/',
    'mp.weixin.qq.com': 'https://mp.weixin.qq.com/',
    'note.youdao.com': 'https://note.youdao.com/',
    'upload-images.jianshu.io': 'https://www.jianshu.com/',
    'p1-jj.byteimg.com': 'https://juejin.cn/',
    'user-gold-cdn.xitu.io': 'https://juejin.cn/',
}

CT_EXT = {
    'image/jpeg': '.jpg',
    'image/jpg': '.jpg',
    'image/pjpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'image/svg+xml': '.svg',
    'image/bmp': '.bmp',
    'image/x-icon': '.ico',
    'image/vnd.microsoft.icon': '.ico',
}

KNOWN_IMG_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico'}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('localize_images')


def load_youdao_cookie(cookies_path: Path) -> str:
    """从 cookies.json 加载 .note.youdao.com 域的 cookie，拼成 Cookie 头。"""
    if not cookies_path.exists():
        return ''
    try:
        data = json.loads(cookies_path.read_text(encoding='utf-8'))
        items = data.get('cookies', [])
        parts = []
        for entry in items:
            if not isinstance(entry, (list, tuple)) or len(entry) < 3:
                continue
            name, value, domain = entry[0], entry[1], entry[2] or ''
            if 'note.youdao.com' in domain:
                parts.append(f'{name}={value}')
        return '; '.join(parts)
    except Exception as e:
        log.warning("解析 %s 失败：%s", cookies_path, e)
        return ''


_YOUDAO_COOKIE = load_youdao_cookie(COOKIES_PATH)
if _YOUDAO_COOKIE:
    log.info("已加载有道云 Cookie（%d 个键），将用于 note.youdao.com 域的图片下载。",
             _YOUDAO_COOKIE.count('=') )
else:
    log.warning("未找到 %s，note.youdao.com 域的图片可能因未登录而下载失败。",
                COOKIES_PATH)


# 全局缓存：URL → (bytes, ext)；同 URL 多 md 引用时不重复下载
_url_cache: dict[str, tuple[bytes, str]] = {}
_url_cache_lock = threading.Lock()

# 失败 URL 记录：URL → (error, [md_paths])
_url_failed: dict[str, str] = {}
_failed_lock = threading.Lock()


def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode('utf-8')).hexdigest()


def guess_ext_from_url(url: str) -> str:
    """从 URL path 推断扩展名；推断不出则返回空串。"""
    path = urlparse(url).path
    ext = Path(path).suffix.lower()
    if ext in KNOWN_IMG_EXTS:
        return '.jpg' if ext == '.jpeg' else ext
    return ''


def guess_ext_from_ct(ct: str) -> str:
    base = (ct or '').split(';')[0].strip().lower()
    return CT_EXT.get(base, '')


def is_remote(url: str) -> bool:
    return url.startswith(('http://', 'https://'))


def should_skip(url: str) -> bool:
    return url.startswith(SKIP_PREFIXES) or not is_remote(url)


def fetch_image(url: str) -> tuple[Optional[bytes], str, str]:
    """下载 URL，返回 (data, ext, error)。失败时 data=None。"""
    headers = dict(DEFAULT_HEADERS)
    host = (urlparse(url).hostname or '').lower()
    for h, ref in REFERER_MAP.items():
        if host.endswith(h):
            headers['Referer'] = ref
            break
    # 有道云图床需要登录态 cookie，否则返回 HTTP 500
    if _YOUDAO_COOKIE and 'note.youdao.com' in host:
        headers['Cookie'] = _YOUDAO_COOKIE

    last_err = ''
    for attempt in range(DOWNLOAD_RETRIES + 1):
        try:
            with requests.get(url, headers=headers,
                              timeout=DOWNLOAD_TIMEOUT, stream=True) as resp:
                if resp.status_code != 200:
                    last_err = f'HTTP {resp.status_code}'
                    continue
                ct = resp.headers.get('Content-Type', '')
                ext = guess_ext_from_url(url) or guess_ext_from_ct(ct)
                buf = bytearray()
                for chunk in resp.iter_content(chunk_size=16384):
                    if chunk:
                        buf.extend(chunk)
                        if len(buf) > MAX_IMG_BYTES:
                            return None, '', f'image too large (>{MAX_IMG_BYTES} bytes)'
                if not ext:
                    # 文件头嗅探
                    head = bytes(buf[:12])
                    if head.startswith(b'\x89PNG'):
                        ext = '.png'
                    elif head.startswith(b'\xff\xd8\xff'):
                        ext = '.jpg'
                    elif head.startswith(b'GIF8'):
                        ext = '.gif'
                    elif head.startswith(b'RIFF') and b'WEBP' in head:
                        ext = '.webp'
                    elif head.startswith(b'<svg') or head[:5] == b'<?xml':
                        ext = '.svg'
                    else:
                        return None, '', f'unknown image type (CT={ct})'
                return bytes(buf), ext, ''
        except requests.RequestException as e:
            last_err = type(e).__name__ + ': ' + str(e)[:100]
    return None, '', last_err


def fetch_image_cached(url: str) -> tuple[Optional[bytes], str, str]:
    """带全局缓存的下载。"""
    with _url_cache_lock:
        cached = _url_cache.get(url)
        if cached:
            return cached[0], cached[1], ''
    with _failed_lock:
        if url in _url_failed:
            return None, '', _url_failed[url]

    data, ext, err = fetch_image(url)
    if data is not None:
        with _url_cache_lock:
            _url_cache[url] = (data, ext)
    else:
        with _failed_lock:
            _url_failed[url] = err
    return data, ext, err


def collect_urls(text: str) -> list[str]:
    """提取 md 中所有需要下载的远程图片 URL（保持顺序、去重）。"""
    seen: list[str] = []
    seen_set: set[str] = set()
    for m in IMG_RE.finditer(text):
        url = m.group(2)
        if should_skip(url):
            continue
        if url not in seen_set:
            seen_set.add(url)
            seen.append(url)
    return seen


def process_md(md_path: Path, dry_run: bool) -> tuple[int, int, int, int]:
    """返回 (n_skipped, n_ok, n_failed, n_total_in_file)。"""
    try:
        text = md_path.read_text(encoding='utf-8', errors='ignore')
    except Exception as e:
        log.error("读取失败 %s：%s", md_path, e)
        return (0, 0, 0, 0)

    all_urls = [m.group(2) for m in IMG_RE.finditer(text)]
    if not all_urls:
        return (0, 0, 0, 0)

    remote_urls = collect_urls(text)
    if not remote_urls:
        return (len(all_urls), 0, 0, len(all_urls))

    img_dir = md_path.parent / 'images'
    # URL → 相对路径（写入 md 用）
    url_to_rel: dict[str, str] = {}
    n_ok = n_fail = 0

    for url in remote_urls:
        if dry_run:
            ext = guess_ext_from_url(url) or '.?'
            url_to_rel[url] = f'images/{md5_hex(url)[:16]}{ext}'
            n_ok += 1
            continue

        data, ext, err = fetch_image_cached(url)
        if data is None:
            n_fail += 1
            log.warning("    × %s -> %s", url[:80], err)
            continue
        # 写入本目录
        filename = md5_hex(url)[:16] + ext
        local_path = img_dir / filename
        if not local_path.exists():
            img_dir.mkdir(parents=True, exist_ok=True)
            try:
                local_path.write_bytes(data)
            except Exception as e:
                n_fail += 1
                log.warning("    × 写入失败 %s：%s", local_path, e)
                continue
        url_to_rel[url] = f'images/{filename}'
        n_ok += 1

    if url_to_rel and not dry_run:
        def replace_one(m: re.Match) -> str:
            url = m.group(2)
            new_url = url_to_rel.get(url)
            return f'![{m.group(1)}]({new_url})' if new_url else m.group(0)
        new_text = IMG_RE.sub(replace_one, text)
        if new_text != text:
            md_path.write_text(new_text, encoding='utf-8')

    n_skip = len(all_urls) - len(remote_urls)
    return (n_skip, n_ok, n_fail, len(all_urls))


def cleanup_failed_refs(md_files: list[Path], failed_urls: set[str]) -> tuple[int, int]:
    """把所有引用 failed_urls 的图片引用从 md 中清除。"""
    n_files = n_refs = 0
    for f in md_files:
        try:
            t = f.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        before = len(IMG_RE.findall(t))
        new = IMG_RE.sub(
            lambda m: '' if m.group(2) in failed_urls else m.group(0), t)
        after = len(IMG_RE.findall(new))
        if before != after:
            f.write_text(new, encoding='utf-8')
            n_files += 1
            n_refs += (before - after)
    return n_files, n_refs


def cleanup_data_image_placeholders(md_files: list[Path]) -> tuple[int, int]:
    """清理 ![](.../data:image/...) 这种伪 URL 占位图（含空格也清掉）。"""
    pat = re.compile(r'!\[[^\]]*\]\([^)]*data:image[^)]*\)')
    n_files = n_refs = 0
    for f in md_files:
        try:
            t = f.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        new, n = pat.subn('', t)
        if n:
            f.write_text(new, encoding='utf-8')
            n_files += 1
            n_refs += n
    return n_files, n_refs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true',
                        help='只统计/打印将要下载的内容，不实际写入')
    parser.add_argument('--concurrency', type=int, default=8,
                        help='并发处理 md 数量')
    parser.add_argument('--root', default=str(ROOT))
    parser.add_argument('--cleanup-failed', action='store_true', default=True,
                        help='下载结束后，把仍然失败的图片引用从 md 中清除（默认开启）')
    parser.add_argument('--no-cleanup-failed', action='store_false',
                        dest='cleanup_failed',
                        help='禁用失败引用清理，保留原 URL（导入后会显示坏图）')
    parser.add_argument('--cleanup-data-placeholder', action='store_true', default=True,
                        help='清理 ![](.../data:image/...) 伪 URL 占位图（默认开启）')
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        log.error("目录不存在：%s", root)
        sys.exit(1)

    md_files = sorted(root.rglob('*.md'))
    log.info("待扫描 md 文件：%d 个", len(md_files))

    total_skip = total_ok = total_fail = total_imgs = 0
    processed = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(process_md, f, args.dry_run): f for f in md_files}
        for fut in as_completed(futs):
            f = futs[fut]
            processed += 1
            try:
                ns, nok, nf, ntot = fut.result()
            except Exception as e:
                log.error("[%d/%d] 处理 %s 抛异常：%s",
                          processed, len(md_files), f.relative_to(root), e)
                continue
            total_skip += ns
            total_ok += nok
            total_fail += nf
            total_imgs += ntot
            if nok or nf:
                log.info("[%d/%d] %s  ok=%d fail=%d skip=%d",
                         processed, len(md_files), f.relative_to(root),
                         nok, nf, ns)

    log.info("=" * 60)
    log.info("文件总数: %d  图片引用总数: %d", len(md_files), total_imgs)
    log.info("远程图下载: ok=%d  fail=%d", total_ok, total_fail)
    log.info("跳过(本地相对/data:/安卓路径): %d", total_skip)
    log.info("缓存命中的 URL 数: %d", len(_url_cache))

    if _url_failed and not args.dry_run:
        # 收集每个失败 URL 在哪些 md 文件出现过
        url_to_files: dict[str, list[str]] = {}
        for md in md_files:
            try:
                txt = md.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            for m in IMG_RE.finditer(txt):
                url = m.group(2)
                if url in _url_failed:
                    url_to_files.setdefault(url, []).append(
                        str(md.relative_to(root)))

        with open(FAIL_LOG, 'w', encoding='utf-8') as fp:
            fp.write(f"# 共 {len(_url_failed)} 个 URL 下载失败\n")
            for url, err in _url_failed.items():
                fp.write(f"\nURL: {url}\nError: {err}\nReferenced by:\n")
                for p in url_to_files.get(url, []):
                    fp.write(f"  - {p}\n")
        log.info("失败明细已写入：%s", FAIL_LOG)

    if not args.dry_run and args.cleanup_failed and _url_failed:
        nf, nr = cleanup_failed_refs(md_files, set(_url_failed.keys()))
        log.info("已清理 %d 处失效图片引用（涉及 %d 个 md）。", nr, nf)

    if not args.dry_run and args.cleanup_data_placeholder:
        nf, nr = cleanup_data_image_placeholders(md_files)
        if nr:
            log.info("已清理 %d 处 data:image 占位伪 URL（涉及 %d 个 md）。", nr, nf)


if __name__ == '__main__':
    main()
