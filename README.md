# youdao2yuque

> **把有道云笔记完整搬家到语雀**——拉取、格式转换、图片本地化、附件修复、一键打包导入。

[English](./README.en.md) · [License](./LICENSE)

![python](https://img.shields.io/badge/python-3.9%2B-blue) ![license](https://img.shields.io/badge/license-MIT-green) ![status](https://img.shields.io/badge/status-stable-success)

---

## 这个项目解决什么问题？

你想把多年沉淀在**有道云笔记**里的笔记迁移到**语雀**，但你会撞到下面这堆事：

- 有道云不再支持官方导出，但还允许"按笔记下载"
- 下载下来的 `.note` 文件是私有 XML/JSON，不是 markdown
- 笔记里的图片只能在有道云笔记里看，迁出去全是坏图
- 把笔记打包成 zip 上传语雀，导入失败——错误是"Maximum call stack size exceeded"，但没人告诉你原因
- PDF 附件链接挂着但点击下载不到
- 语雀 V2 API 已经只对付费用户开放

这个工具链解决了上述**全部**问题。作者用它把自己 **218 篇笔记 / 736 张图 / 115 个 PDF** 全量迁到语雀，过程中遇到的每个坑都打了补丁。

---

## 功能总览

```
有道云笔记                                                            语雀
   │                                                                  ▲
   │ ① pull.py                                                        │
   ▼          ② convert_to_md   ③ localize_images   ④ fix_*           │
本地 .note ───────────► markdown ───────────► markdown ──► 打包 zip ──┘
   原始格式            带远程图          + 本地图 + 附件                ⑤ Web 导入
```

| 阶段 | 脚本 | 作用 |
|---|---|---|
| ① 拉取 | `pull.py` | 用浏览器 cookie 调用有道云内部 API，按目录结构下载所有笔记到本地（基于 [DeppWang/youdaonote-pull](https://github.com/DeppWang/youdaonote-pull)） |
| ② 格式转换 | `convert_to_md.py` | 把 `.note` / 无扩展名文件 / XML / JSON / HTML 片段统一转成 markdown |
| ③ 图片本地化 | `localize_images.py` | 扫描 md 里的远程图 URL，并发下载并改写为本地 `images/` 路径；支持 cookie 鉴权下载有道图床 |
| ④ 兼容性修复 | `fix_naked_html.py`<br>`fix_attachment_links.py`<br>`normalize_attachment_names.py` | 转义裸 HTML 标签、给坏链接加 `<>` 包裹、规范化附件文件名——根治语雀导入失败 |
| ⑤ 打包导入 | `zip` + 语雀 Web 导入 | 打 zip 后在语雀知识库的「导入」入口选择「本地导入」上传 |

---

## 快速上手

### 0. 环境

- Python 3.9+
- macOS / Linux / Windows 均可（脚本平台无关）

```bash
git clone https://github.com/zhengoma/youdao2yuque.git
cd youdao2yuque
pip install -r requirements.txt
```

### 1. 准备 cookie

```bash
cp cookies.example.json cookies.json
```

打开浏览器登录 [note.youdao.com](https://note.youdao.com)，按 F12 → Application → Cookies，把 `YNOTE_CSTK`、`YNOTE_LOGIN`、`YNOTE_SESS` 三个值填进 `cookies.json`。

> ⚠️ `cookies.json` 已在 `.gitignore`，不会被提交。

### 2. 拉取所有笔记

```bash
python3 pull.py
```

会把笔记按原目录结构下载到 `./youdaonote/` 下。耗时取决于笔记数量。

### 3. 转换 `.note` 为 markdown

```bash
python3 convert_to_md.py ./youdaonote --dry-run   # 先预览
python3 convert_to_md.py ./youdaonote             # 实际执行
```

### 4. 本地化远程图片

```bash
python3 localize_images.py --root ./youdaonote --concurrency 8
```

需要鉴权的图（有道图床）会用 `cookies.json` 自动登录。失败列表写到 `image-download-failures.log`。

### 5. 修复语雀导入兼容性

```bash
python3 fix_naked_html.py ./youdaonote                # 转义裸 HTML
python3 fix_attachment_links.py ./youdaonote          # 修 URL 含 ()/空格 的链接
python3 normalize_attachment_names.py ./youdaonote    # 规范化附件文件名（去 ASCII 括号）
```

### 6. 打包 + 导入语雀

```bash
zip -r youdao2yuque-final.zip youdaonote -x '*.DS_Store'
```

打开语雀知识库 → 设置 → 导入 → 选择「本地导入」→ 上传 zip，等待几分钟即可。

---

## 一些踩坑总结（值得看）

| 坑 | 原因 | 这里怎么解决 |
|---|---|---|
| `pip install` 报 `win32-setctime` 在 macOS/Linux 装不上 | 上游 requirements 没做平台门控 | `requirements.txt` 加了 `; sys_platform == "win32"` |
| 语雀导入"Maximum call stack size exceeded" | 笔记里有大量裸 HTML 标签 + 不配对的 markdown 方括号，撑爆解析器栈 | `fix_naked_html.py` 转义裸标签 |
| PDF 链接显示但**点击下载失败** | 文件名含 ASCII 半角 `(1)`，语雀附件上传时把名字搞坏 | `normalize_attachment_names.py` 把 `xxx (1).pdf` 重命名为 `xxx_1.pdf`，同步改 md 引用 |
| 远程图 403/500 | 有道图床要求登录态 | `localize_images.py` 自动加载 `cookies.json` 调下载 |
| 语雀 V2 API 不可用 | Token 现在仅付费用户可申请 | 本项目走 zip Web 导入，无需 Token |

---

## 致谢

- [@DeppWang](https://github.com/DeppWang) — [youdaonote-pull](https://github.com/DeppWang/youdaonote-pull) 提供了优秀的有道云笔记拉取实现，本项目的 `pull.py` 和 `core/` 直接来自该项目。
- 所有踩过坑、给原仓库提过 issue/PR 的同学。

---

## 协议

[MIT](./LICENSE) — 同上游 `youdaonote-pull` 一致。本项目在原 MIT 协议下衍生，沿用并扩展。

---

## 免责声明

- 本工具仅供**用户本人**对**自己账号**下的数据做迁移备份使用。
- 所有 cookie 均由用户在本地填写并保存在本地，**不会上传到任何服务器**。
- 使用本工具产生的任何后果由使用者自行承担。
- 请遵守有道云笔记和语雀的用户协议。
