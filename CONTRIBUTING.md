# Contributing

欢迎贡献！本项目是个人迁移工具链的开源化，但欢迎所有有道云笔记 / 语雀生态的用户加入。

## 你可以做什么

1. **报告 bug**：在你自己的迁移过程中遇到了新的"坑"——开 [Issue](../../issues) 描述清楚环境和复现步骤
2. **补充修复脚本**：碰到新的"语雀拒绝接受"的格式问题，欢迎贡献新的 `fix_*.py`
3. **改进文档**：步骤不清楚、缺截图、英文翻译可改进
4. **扩展能力**：例如增加对印象笔记、Notion 等源的支持，或对 Obsidian、Logseq 等目标的支持

## 开发流程

```bash
git clone https://github.com/<your-name>/youdao2yuque.git
cd youdao2yuque
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pre-commit
pre-commit install
```

提交前会自动跑 black + isort + flake8。

## 风格

- Python 3.9+
- 命令行入口都用 `argparse`，支持 `--dry-run`
- 任何对用户数据有破坏性的操作（删除文件、重命名、改写内容）默认必须有 `--dry-run` 预览
- 不在脚本里硬编码用户路径；用 CLI 参数或环境变量
- 不提交任何含真实 cookie / token 的文件

## 安全

- 凭证文件（`cookies.json` / `.env` / `*.token`）已在 `.gitignore`
- 如发现安全问题，请直接邮件作者而非开公开 Issue
