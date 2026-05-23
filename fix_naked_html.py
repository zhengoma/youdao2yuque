#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
扫描指定 md 文件 / 目录，把「裸露的 HTML 标签」做反斜杠转义。

为什么需要：
    语雀网页端的 markdown 解析器在遇到大量嵌套或异常 HTML（如裸露的
    <div>/<p>/Vue 自定义组件 <router-link> 等）时可能递归过深，
    导入时报 "Maximum call stack size exceeded"。把这些标签转义为
    \<div\> 之后，解析器视为字面文字，从根本上绕开爆栈。

特性：
    - 跳过 ``` ``` 代码块内的内容（真代码不动）
    - 用 lookbehind 跳过已转义的 \<tag\>（重复跑也幂等）
    - 支持 --dry-run 预览
    - 支持传文件或目录路径；目录会递归 *.md
    - 默认阈值 5：只处理裸 HTML 标签数 >=5 的文件，避免无端改动

用法：
    # 修单个文件
    python3 fix_naked_html.py path/to/note.md

    # 扫描整个目录、阈值 30 起处理
    python3 fix_naked_html.py ./youdaonote --threshold 30

    # 仅预览要改哪些文件
    python3 fix_naked_html.py ./youdaonote --dry-run
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

# 匹配：未被前置反斜杠转义的 <tag ...> 或 </tag>
TAG_RE = re.compile(
    r'(?<!\\)<(/?[a-zA-Z][a-zA-Z0-9_-]*(?:\s+[^<>]*)?(?:\s*/)?)>'
)
# 拆分代码块用：捕获 ```...``` 整段
FENCE_SPLIT_RE = re.compile(r'(```[\s\S]*?```)')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('fix_naked_html')


def escape_naked_html_outside_fences(text: str) -> tuple[str, int]:
    """把 ``` 围栏之外的裸 HTML 标签转义。返回 (新文本, 替换数量)。"""
    parts = FENCE_SPLIT_RE.split(text)
    n_total = 0
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            # 奇数索引是 ```...``` 围栏内容，保持原样
            out.append(part)
            continue
        n = len(TAG_RE.findall(part))
        if n:
            part = TAG_RE.sub(lambda m: r'\<' + m.group(1) + r'\>', part)
            n_total += n
        out.append(part)
    return ''.join(out), n_total


def count_naked_tags(text: str) -> int:
    """统计 ``` 围栏外的裸 HTML 标签数（用于判断是否需要修复）。"""
    parts = FENCE_SPLIT_RE.split(text)
    return sum(len(TAG_RE.findall(p)) for i, p in enumerate(parts) if i % 2 == 0)


def iter_md(path: Path):
    if path.is_file():
        if path.suffix.lower() in ('.md', '.markdown'):
            yield path
    elif path.is_dir():
        yield from sorted(path.rglob('*.md'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('targets', nargs='+',
                        help='md 文件或目录（多个）')
    parser.add_argument('--threshold', type=int, default=5,
                        help='只处理裸 HTML 标签数 >= 此阈值的文件，默认 5')
    parser.add_argument('--dry-run', action='store_true',
                        help='只预览要改哪些文件')
    args = parser.parse_args()

    md_files: list[Path] = []
    for t in args.targets:
        p = Path(t).expanduser().resolve()
        if not p.exists():
            log.error("路径不存在：%s", p)
            sys.exit(1)
        md_files.extend(iter_md(p))

    if not md_files:
        log.error("没扫到任何 .md 文件。")
        sys.exit(1)

    log.info("待检查 md 文件：%d", len(md_files))
    n_files_changed = n_total = 0
    for f in md_files:
        try:
            text = f.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            log.error("读取失败 %s：%s", f, e)
            continue
        n_before = count_naked_tags(text)
        if n_before < args.threshold:
            continue
        if args.dry_run:
            log.info("[dry-run] 会修复 %d 个标签 -> %s", n_before, f)
            n_files_changed += 1
            n_total += n_before
            continue
        new_text, n = escape_naked_html_outside_fences(text)
        if n > 0 and new_text != text:
            f.write_text(new_text, encoding='utf-8')
            n_files_changed += 1
            n_total += n
            log.info("已修复 %3d 个标签：%s", n, f)

    log.info("=" * 60)
    log.info("文件影响：%d，转义标签总数：%d", n_files_changed, n_total)


if __name__ == '__main__':
    main()
