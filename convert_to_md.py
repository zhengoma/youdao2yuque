#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 youdaonote/ 目录里所有「非 markdown」的笔记文件原地转换为 .md。

覆盖的文件类型（按文件头自动识别）：
    1) 有道云 XML 格式：  <?xml ... <note xmlns="http://note.youdao.com">  -> .md
    2) 有道云 JSON 格式： {"...                                            -> .md
    3) HTML 片段：       <div>/<p> 等                                      -> .md（markdownify）

跳过：
    - 已经是 .md / .markdown 的文件
    - images/ attachments/ 目录里的所有内容
    - 二进制资源（png/jpg/pdf/zip 等）
    - .DS_Store

用法：
    # 1) 先 dry-run 看一遍要动哪些文件
    python3 convert_to_md.py --dry-run

    # 2) 真的转换
    python3 convert_to_md.py

转换后原始 .note / 无扩展名文件会被删除；如果同名 .md 已存在，会写到
`<原名>.from-note.md` 防止覆盖。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# 让脚本能 import 同目录下的 core.* 模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.covert import YoudaoNoteConvert  # noqa: E402

import re  # noqa: E402

try:
    from markdownify import markdownify as html_to_md  # noqa: E402
except ImportError:
    print("缺少依赖：请先运行 pip3 install markdownify", file=sys.stderr)
    sys.exit(1)


# markdownify 转出来的内容里常有大量裸露的 HTML 标签（<div>/<p>/<my-component>），
# 语雀这类网页端 markdown 解析器在处理深嵌套或异常 HTML 时可能递归爆栈
# (Maximum call stack size exceeded)。此处把所有形如 <tag ...> 的尖括号串
# 转义为 \<tag ...\>，让解析器视为字面文字。代价是显示时带反斜杠，
# 但能 100% 避免导入失败。
_HTML_TAG_RE = re.compile(r"<(/?[a-zA-Z][a-zA-Z0-9_-]*(?:\s+[^<>]*)?(?:\s*/)?)>")


def escape_naked_html(text: str) -> str:
    return _HTML_TAG_RE.sub(lambda m: r"\<" + m.group(1) + r"\>", text)


# ============================ 配置 ============================
# 默认扫描目录；运行时可用第一个位置参数覆盖
LOCAL_ROOT = "./youdaonote"

# 这些目录里的内容不动（资源目录）
IGNORE_DIR_NAMES = {"images", "attachments", "__MACOSX"}
IGNORE_FILE_NAMES = {".DS_Store"}

# 已经是 markdown 的文件直接跳过
MARKDOWN_EXTS = {".md", ".markdown"}

# 已知二进制 / 资源扩展名（跳过）
BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".mp3", ".mp4", ".mov", ".avi", ".webm", ".m4a",
    ".exe", ".dmg", ".pkg",
}
# ==============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("convert_to_md")


def detect_format(file_path: Path) -> str:
    """识别内容格式：'xml' / 'json' / 'html' / 'binary' / 'empty'."""
    try:
        with open(file_path, "rb") as f:
            head = f.read(16)
    except Exception as e:
        log.warning("读取失败 %s：%s", file_path, e)
        return "binary"
    if not head:
        return "empty"
    if head[:5] == b"<?xml":
        return "xml"
    # 有道云 JSON 通常以 {" 开头；普通 JSON 也行
    if head[:1] == b"{":
        return "json"
    # 尝试当作文本（HTML 片段）
    try:
        head.decode("utf-8")
        return "html"
    except UnicodeDecodeError:
        return "binary"


# 已知的"有道云笔记原生后缀"，转换时这些后缀会被剥掉再换成 .md。
# 文件名里其它形如 .NET / .COM / .js 的 "伪扩展名"（其实是标题的一部分）
# 必须保留，否则会丢失大量信息。
KNOWN_NOTE_EXTS = {".note", ".clip"}


def unique_md_path(file_path: Path) -> Path:
    """计算目标 .md 路径；若同名已存在则加 .from-note 后缀避让。

    规则：
        - 若文件真扩展名是 .note / .clip：剥掉后再追加 .md。
        - 否则（无扩展名 / 标题里带点号）：整个文件名 + ".md"。
    """
    ext = file_path.suffix.lower()
    if ext in KNOWN_NOTE_EXTS:
        stem = file_path.with_suffix("")  # 去掉真扩展名
    else:
        stem = file_path  # 整名都是标题

    target = stem.parent / (stem.name + ".md")
    if not target.exists():
        return target
    candidate = stem.parent / f"{stem.name}.from-note.md"
    n = 1
    while candidate.exists():
        candidate = stem.parent / f"{stem.name}.from-note-{n}.md"
        n += 1
    return candidate


def convert_one(file_path: Path, dry_run: bool) -> str:
    """转换单个文件。返回 ok / fail / skip-binary / skip-empty。"""
    fmt = detect_format(file_path)
    if fmt in ("binary", "empty"):
        log.info("[skip-%s] %s", fmt, file_path.name)
        return f"skip-{fmt}"

    target = unique_md_path(file_path)

    if dry_run:
        log.info("[dry-run] %s  ->  %s  (fmt=%s)",
                 file_path.name, target.name, fmt)
        return "ok"

    try:
        if fmt == "xml":
            content = YoudaoNoteConvert._covert_xml_to_markdown_content(str(file_path))
        elif fmt == "json":
            content = YoudaoNoteConvert._covert_json_to_markdown_content(str(file_path))
        else:  # html
            with open(file_path, "rb") as f:
                raw = f.read()
            html = raw.decode("utf-8", errors="ignore")
            content = html_to_md(html)
            content = escape_naked_html(content)
    except Exception as e:
        log.error("转换失败 %s（fmt=%s）：%s", file_path, fmt, e)
        return "fail"

    try:
        target.write_text(content or "", encoding="utf-8")
    except Exception as e:
        log.error("写入失败 %s：%s", target, e)
        return "fail"

    try:
        file_path.unlink()
    except Exception as e:
        log.warning("删除原文件失败（不影响转换结果） %s：%s", file_path, e)

    log.info("[ok-%s] %s  ->  %s", fmt, file_path.name, target.name)
    return "ok"


def collect_candidates(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIR_NAMES]
        for name in filenames:
            if name in IGNORE_FILE_NAMES:
                continue
            p = Path(dirpath) / name
            ext = p.suffix.lower()
            if ext in MARKDOWN_EXTS:
                continue
            if ext in BINARY_EXTS:
                continue
            out.append(p)
    out.sort()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="把 youdaonote/ 下非 md 笔记原地转 md")
    parser.add_argument("--dry-run", action="store_true",
                        help="只显示会动哪些文件，不真的写入或删除")
    parser.add_argument("--root", default=LOCAL_ROOT, help="扫描根目录")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        log.error("目录不存在：%s", root)
        sys.exit(1)

    candidates = collect_candidates(root)
    log.info("根目录：%s", root)
    log.info("发现 %d 个待处理文件。", len(candidates))
    if not candidates:
        return

    stats: dict[str, int] = {}
    for i, p in enumerate(candidates, 1):
        rel = p.relative_to(root)
        log.info("[%d/%d] %s", i, len(candidates), rel)
        result = convert_one(p, args.dry_run)
        stats[result] = stats.get(result, 0) + 1

    log.info("=" * 60)
    log.info("结果统计：%s", stats)
    if stats.get("fail"):
        log.warning("有 %d 个文件转换失败，原文件已保留，请翻日志定位。",
                    stats["fail"])
    if not args.dry_run and stats.get("ok"):
        log.info("提示：原始 .note / 无扩展名文件已删除（成功项），如需上传语雀，可重新打包 zip：\n"
                 "  rm -f youdaonote-import.zip && "
                 "zip -r -q youdaonote-import.zip youdaonote -x '*.DS_Store'")


if __name__ == "__main__":
    main()
