#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复 markdown 里"URL 含括号/空格的本地附件链接"。

问题：
    Markdown 链接 [text](url) 的 url 如果含 `(` `)` 或空格（如有道云笔记
    导出常见的 `xxx(1).pdf`），解析器会在第一个 `)` 处截断，导致整个链接
    失效，语雀里看到的是一段裸文字而不是可点击的下载链接。

修复：
    按 CommonMark 规范用 <> 包裹 url：
        [text](attachments/xxx (1).pdf)   ->   [text](<attachments/xxx (1).pdf>)
    <> 形式允许 url 内含括号、空格等字符。

用法：
    python3 fix_attachment_links.py ./youdaonote                  # 修整个目录
    python3 fix_attachment_links.py ./youdaonote/<subdir>         # 修指定子目录
    python3 fix_attachment_links.py path/to/note.md               # 修单文件
    python3 fix_attachment_links.py ./youdaonote --dry-run        # 只预览
    python3 fix_attachment_links.py ./youdaonote --include-spaces # 顺便修仅含空格的
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('fix_attachment_links')

# 仅匹配指向本地资源（扩展名白名单）的链接，避免误改普通 http 链接
LOCAL_EXTS = (
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'zip', 'rar', '7z', 'tar', 'gz',
    'note', 'md', 'markdown', 'txt', 'rtf',
    'mp3', 'mp4', 'mov', 'avi', 'mkv', 'webm',
)
EXT_GROUP = '|'.join(LOCAL_EXTS)

# 匹配 ![alt](url) 或 [text](url)；url 不含 < > （即不是已经 <> 包裹的）
# url 必须以白名单扩展名结尾，且不是 http(s) 链接
LINK_RE = re.compile(
    rf'(!?)\[([^\[\]\n]*)\]\((?!<)((?!https?://)[^\n<>]*?\.(?:{EXT_GROUP}))\)',
    re.IGNORECASE,
)


def needs_wrap(url: str, include_spaces: bool) -> bool:
    """url 是否需要 <> 包裹。"""
    if '(' in url or ')' in url:
        return True
    if include_spaces and ' ' in url:
        return True
    return False


def fix_text(text: str, include_spaces: bool) -> tuple[str, int]:
    n = 0

    def repl(m: re.Match) -> str:
        nonlocal n
        excl, alt, url = m.group(1), m.group(2), m.group(3)
        if needs_wrap(url, include_spaces):
            n += 1
            return f'{excl}[{alt}](<{url}>)'
        return m.group(0)

    return LINK_RE.sub(repl, text), n


def iter_md(p: Path):
    if p.is_file() and p.suffix.lower() in ('.md', '.markdown'):
        yield p
    elif p.is_dir():
        yield from sorted(p.rglob('*.md'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('target', help='要扫描的 md 文件或目录')
    parser.add_argument('--dry-run', action='store_true',
                        help='只打印将要修改的链接，不真正改文件')
    parser.add_argument('--include-spaces', action='store_true',
                        help='顺便修复 url 仅含空格的链接（默认只修含括号的硬伤）')
    args = parser.parse_args()

    p = Path(args.target).expanduser().resolve()
    if not p.exists():
        log.error("路径不存在：%s", p)
        sys.exit(1)

    n_files_changed = n_total = 0
    for f in iter_md(p):
        try:
            text = f.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            log.error("读取失败 %s：%s", f, e)
            continue
        new_text, n = fix_text(text, args.include_spaces)
        if n == 0:
            continue
        if args.dry_run:
            log.info("[dry-run] %s  会修复 %d 个链接", f, n)
            n_files_changed += 1
            n_total += n
            # 打印 diff 样本
            for m in LINK_RE.finditer(text):
                if needs_wrap(m.group(3), args.include_spaces):
                    log.info("    %s", m.group(0)[:200])
            continue
        if new_text != text:
            f.write_text(new_text, encoding='utf-8')
            log.info("已修复 %d 个链接：%s", n, f)
            n_files_changed += 1
            n_total += n

    log.info("=" * 60)
    log.info("文件影响：%d，链接修复总数：%d", n_files_changed, n_total)


if __name__ == '__main__':
    main()
