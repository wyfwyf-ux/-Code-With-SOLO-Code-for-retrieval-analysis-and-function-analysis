# 自我帮助小助手

一个本地运行的资料与代码项目扫描工具，用来快速回答：

- 我的文档大概散落在哪里？
- 某个项目里有哪些代码、文档、大文件和待办标记？
- 代码项目里有哪些函数？每个函数大概做什么？
- 最近改过哪些资料？
- 哪些文件可能值得整理、归档或继续阅读？

## 快速使用

```powershell
python .\self_help_assistant.py "F:\Desktop\xla" "F:\Desktop\研二下" --query "leetcode" --query "组会"
```

启动可交互小助手页面：

```powershell
python .\local_server.py --port 8765
```

然后浏览器打开：

```text
http://127.0.0.1:8765/
```

只有通过这个本地服务打开页面时，点击“开始分析”才会自动运行脚本；直接双击 HTML 打开的 `file://` 页面只能做静态演示。

默认会生成：

- `self_help_report.md`：适合阅读和截图的 Markdown 报告
- `self_help_index.json`：可继续喂给 AI 分析的结构化索引

生成参赛帖图片：

```powershell
python .\visualize_assets.py
```

图片会保存到 `assets/`：

- `01_scan_overview.png`：扫描总览
- `02_file_type_distribution.png`：文件类型分布
- `03_code_todo_risks.png`：代码 TODO 风险
- `04_document_keyword_hits.png`：文档关键词命中
- `05_large_files.png`：大文件提醒
- `自我帮助小助手_可视化看板.html`：可截图的看板页面
- `3D桌面展示.html`：小助手交互页，流程为选择任务、输入文件夹路径、展示分析结果和本地命令

## 代码函数级分析

离线分析一个代码文件夹：

```powershell
python .\code_analyzer.py "F:\Desktop\xla" --max-files 80 --out "xla_代码函数分析报告.md" --json-out "code_analysis_index.json"
```

生成代码分析图片：

```powershell
python .\visualize_code_analysis.py
python .\visualize_assets.py
```

会新增：

- `xla_代码函数分析报告.md`：函数级代码分析报告
- `code_analysis_index.json`：函数级结构化索引
- `assets/06_code_analysis_overview.png`：代码分析总览
- `assets/07_function_purpose_cards.png`：函数作用示例
- `代码分析_可视化看板.html`：代码分析专用看板

可选 API 增强：

```powershell
python .\code_analyzer.py "F:\Desktop\xla" --max-files 30 --use-api --provider doubao --api-limit 10
```

模型配置写在当前目录的 `.env` 中，支持：

- `doubao`：读取 `DOUBAO_API_KEY` / `DOUBAO_BASE_URL` / `DOUBAO_MODEL`
- `deepseek`：读取 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL`
- `chatgpt`：读取 `CHATGPT_API_KEY` / `CHATGPT_BASE_URL` / `CHATGPT_MODEL`
- `gemini`：读取 `GEMINI_API_KEY` / `GEMINI_BASE_URL` / `GEMINI_MODEL`

可以参考 `.env.example` 填写。没有 `--use-api` 时完全离线运行。

## 常用参数

```powershell
python .\self_help_assistant.py "F:\Desktop" --max-files 5000 --query "论文" --query "项目"
```

- `--query`：搜索关键词，可以重复传入多个
- `--name`：按文件名搜索，可以只输入文件名里的几个字，例如 `--name "leetcode"`
- `--max-files`：限制扫描数量，避免第一次扫太久
- `--include-vendor`：包含 `third_party`、`node_modules`、`build` 等目录
- `--out`：指定 Markdown 报告输出路径
- `--json-out`：指定 JSON 索引输出路径

只记得文件名时，也可以不传目录，工具会默认扫描 `F:\Desktop`、桌面、文档和当前工具目录：

```powershell
python .\self_help_assistant.py --name "leetcode" --out "文件查找报告.md"
```

## 参赛帖可写亮点

这个工具不是单纯写代码，而是把个人资料管理、代码项目体检和 AI 总结串成一个流程：

1. SOLO 先帮我拆解“自我帮助小助手”的核心能力。
2. SOLO 生成本地扫描脚本，避免资料上传，保护隐私。
3. 工具自动扫描代码项目和学习文档，生成分类、最近修改、大文件、关键词命中、TODO 风险标记。
4. 我再把生成的 Markdown 报告交给 SOLO，让它继续整理成学习计划、项目理解笔记或重构建议。
