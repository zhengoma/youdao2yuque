#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
规范化 attachments/ 目录下的附件文件名，并同步更新所有 markdown 引用。

背景：
    语雀导入 zip 时对文件名里的 ASCII 半角 `(` `)` 处理不一致：
    虽然 markdown 链接已用 <> 包裹能正确显示，但点击却下载不到，
    因为语雀导入器在识别/上传附件那步就把含 `()` 的文件名搞坏了。

规则（仅作用于附件文件名 stem，不动扩展名，不动 md 文档自身的名字）：
    " (1)"  -> "_1"
    "(1)"   -> "_1"
    "(abc)" -> "_abc"
    残留孤立 "(" / ")" 也清理掉
    多个 "_" 合一

同步动作：
    1. 物理重命名 attachments/<old> -> attachments/<new>
    2. 全仓 md 文件中将引用 url 里旧文件名替换为新文件名
    3. 如果旧链接是 <> 包裹的，新链接撤掉 <>（因为新名已无特殊字符）

用法：
    python3 normalize_attachment_names.py youdaonote --dry-run
    python3 normalize_attachment_names.py youdaonote
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
log = logging.getLogger('normalize')


def normalize_name(name: str) -> str:
    p = Path(name)
    stem, ext = p.stem, p.suffix
    stem = re.sub(r'\s*\(([^()]*)\)', r'_\1', stem)
    stem = stem.replace('(', '_').replace(')', '')
    stem = re.sub(r'_+', '_', stem).strip('_')
    return stem + ext


def collect_renames(root: Path) -> list[tuple[Path, Path]]:
    """只扫 attachments/ 目录下、且 stem 含 ( 或 ) 的文件。"""
    renames: list[tuple[Path, Path]] = []
    seen_new: set[Path] = set()
    for f in sorted(root.rglob('*')):
        if not f.is_file():
            continue
        if 'attachments' not in f.parts:
            continue
        if '(' not in f.name and ')' not in f.name:
            continue
        new_name = normalize_name(f.name)
        if new_name == f.name:
            continue
        new_path = f.with_name(new_name)
        if new_path.exists() or new_path in seen_new:
            log.warning("目标名冲突，跳过: %s -> %s", f, new_path)
            continue
        seen_new.add(new_path)
        renames.append((f, new_path))
    return renames


def update_md_references(root: Path, renames: list[tuple[Path, Path]], dry_run: bool) -> int:
    """把所有 md 里对旧文件名的引用替换为新文件名，并撤掉 <> 包裹。"""
    if not renames:
        return 0

    # 构建 旧文件名 -> 新文件名 的映射（只用 basename，因为引用形式是 attachments/basename）
    name_map = {old.name: new.name for old, new in renames}

    n_total_repl = 0
    for md in sorted(root.rglob('*.md')):
        text = md.read_text(encoding='utf-8', errors='ignore')
        original = text
        for old_name, new_name in name_map.items():
            if old_name not in text:
                continue
            # 形态 A: ](<...attachments/old_name>)  ->  ](...attachments/new_name)  (撤掉 <>)
            text = re.sub(
                r'\]\(<([^<>\n]*?)' + re.escape(old_name) + r'>\)',
                lambda m: f']({m.group(1)}{new_name})',
                text,
            )
            # 形态 B: ](...attachments/old_name)   ->  ](...attachments/new_name)
            text = re.sub(
                r'\]\(([^()\n<>]*?)' + re.escape(old_name) + r'\)',
                lambda m: f']({m.group(1)}{new_name})',
                text,
            )
        if text != original:
            n = sum(text.count(new) - original.count(new) for new in name_map.values())
            if dry_run:
                log.info("[dry-run] %s  会更新引用", md.relative_to(root))
            else:
                md.write_text(text, encoding='utf-8')
                log.info("已更新引用: %s", md.relative_to(root))
            n_total_repl += 1
    return n_total_repl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('target', help='youdaonote 根目录')
    parser.add_argument('--dry-run', action='store_true', help='只预览不改')
    args = parser.parse_args()

    root = Path(args.target).expanduser().resolve()
    if not root.is_dir():
        log.error("目录不存在: %s", root)
        sys.exit(1)

    renames = collect_renames(root)
    log.info("计划重命名 attachments 文件: %d 个", len(renames))
    for old, new in renames:
        log.info("  %s", old.name)
        log.info("    -> %s", new.name)

    n_md = update_md_references(root, renames, args.dry_run)
    log.info("受影响 md 文件: %d 个", n_md)

    if args.dry_run:
        log.info("[dry-run] 不执行物理重命名")
        return

    for old, new in renames:
        old.rename(new)
        log.info("已重命名: %s -> %s", old.name, new.name)

    log.info("=" * 60)
    log.info("完成: 重命名 %d 个附件, 更新 %d 个 md", len(renames), n_md)


if __name__ == '__main__':
    main()
