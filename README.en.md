# youdao2yuque

> **Migrate Youdao Note to Yuque, end to end.** Pull, format-convert, image-localize, attachment-fix, zip-pack and import.

[中文](./README.md) · [License](./LICENSE)

![python](https://img.shields.io/badge/python-3.9%2B-blue) ![license](https://img.shields.io/badge/license-MIT-green) ![status](https://img.shields.io/badge/status-stable-success)

---

## What this project solves

You have years of notes in **Youdao Note** (Chinese: 有道云笔记) and want to move them to **Yuque** (语雀). On the way you will hit all of:

- Youdao no longer offers an official export but still allows per-note download
- Downloaded `.note` files are proprietary XML/JSON, not markdown
- Inline images in notes only render inside Youdao Note — outside, they 403
- Zipping the notes and uploading to Yuque fails with `Maximum call stack size exceeded` and no explanation
- PDF attachment links render but don't download
- Yuque V2 API is now paywalled

This toolkit solves every one of those problems. The author migrated **218 notes / 736 images / 115 PDFs** end-to-end using this exact pipeline.

---

## Pipeline

```
Youdao Note                                                            Yuque
   │                                                                    ▲
   │ (1) pull.py                                                        │
   ▼      (2) convert_to_md   (3) localize_images   (4) fix_*           │
local .note ───────► markdown ────────► markdown ────► zip ─────────────┘
   raw            with remote img    + local img + atts    (5) Web import
```

| Stage | Script | What it does |
|---|---|---|
| 1. Pull | `pull.py` | Use browser cookie to call Youdao's internal API and dump notes to local disk, preserving folder hierarchy. (Based on [DeppWang/youdaonote-pull](https://github.com/DeppWang/youdaonote-pull).) |
| 2. Convert | `convert_to_md.py` | Convert `.note` / extensionless / XML / JSON / HTML files to markdown |
| 3. Localize images | `localize_images.py` | Find remote image URLs, download them in parallel into a per-note `images/` folder, rewrite the markdown links. Supports cookie-auth for Youdao's image host |
| 4. Compat fixes | `fix_naked_html.py`<br>`fix_attachment_links.py`<br>`normalize_attachment_names.py` | Escape naked HTML tags, wrap broken URLs with `<>`, normalize attachment filenames — the three things that make Yuque imports fail |
| 5. Pack & import | `zip` + Yuque Web upload | Yuque knowledge base → Import → Local import |

---

## Quick start

### Requirements

- Python 3.9+
- macOS / Linux / Windows

```bash
git clone https://github.com/<your-name>/youdao2yuque.git
cd youdao2yuque
pip install -r requirements.txt
```

### 1. Cookie

```bash
cp cookies.example.json cookies.json
```

Open [note.youdao.com](https://note.youdao.com) in your browser, F12 → Application → Cookies, paste `YNOTE_CSTK`, `YNOTE_LOGIN`, `YNOTE_SESS` into `cookies.json`.

> `cookies.json` is gitignored.

### 2. Pull notes

```bash
python3 pull.py
```

### 3. Convert to markdown

```bash
python3 convert_to_md.py ./youdaonote --dry-run
python3 convert_to_md.py ./youdaonote
```

### 4. Localize images

```bash
python3 localize_images.py --root ./youdaonote --concurrency 8
```

### 5. Fix Yuque-import compatibility

```bash
python3 fix_naked_html.py ./youdaonote
python3 fix_attachment_links.py ./youdaonote
python3 normalize_attachment_names.py ./youdaonote
```

### 6. Pack & import

```bash
zip -r youdao2yuque-final.zip youdaonote -x '*.DS_Store'
```

Then on Yuque: Knowledge Base → Settings → Import → Local import → upload the zip.

---

## Notable gotchas (worth reading)

| Symptom | Root cause | Fix here |
|---|---|---|
| `pip install` fails on Linux/macOS: `win32-setctime` not installable | Upstream requirements lacks platform marker | `requirements.txt` patched with `; sys_platform == "win32"` |
| Yuque import fails with `Maximum call stack size exceeded` | Notes contain unescaped raw HTML and unpaired `[`/`]` brackets | `fix_naked_html.py` escapes them |
| PDF link renders but won't download | Filename contains ASCII `(1)`; Yuque mangles it during attachment upload | `normalize_attachment_names.py` renames `xxx (1).pdf` → `xxx_1.pdf` and updates references |
| Remote images return 403/500 | Youdao's image CDN requires a logged-in session | `localize_images.py` automatically loads `cookies.json` |
| Yuque V2 API unavailable | Tokens are now a paid feature | This project uses zip Web import, no token needed |

---

## Acknowledgements

- [@DeppWang](https://github.com/DeppWang) — the [youdaonote-pull](https://github.com/DeppWang/youdaonote-pull) project provides the excellent Youdao Note pull implementation; `pull.py` and `core/` here come from there.

---

## License

[MIT](./LICENSE) — same as upstream `youdaonote-pull`.

---

## Disclaimer

- This tool is for migrating **your own data** out of **your own account** only.
- Cookies are stored locally and never uploaded anywhere by this tool.
- You are responsible for compliance with Youdao Note and Yuque terms of service.
