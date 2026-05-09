#!/usr/bin/env python
"""Create a polished Chinese text summary from code_analysis_index.json."""

import collections
import json
import os
from pathlib import Path


BASE = Path(__file__).resolve().parent
INDEX = BASE / "code_analysis_index.json"
OUT = BASE / "xla_代码分析文字版.md"


def load_data():
    return json.loads(INDEX.read_text(encoding="utf-8-sig"))


def short(text, limit=120):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def top_dir(relative):
    parts = Path(relative).parts
    return parts[0] if parts else "."


def middle_dir(relative):
    parts = Path(relative).parts
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0] if parts else "."


def function_type(fn):
    name = fn["name"].lower()
    purpose = (fn.get("purpose") or "").lower()
    if "test" in name or "测试" in purpose:
        return "测试验证"
    if any(k in name for k in ("parse", "load", "read", "decode")):
        return "读取解析"
    if any(k in name for k in ("build", "make", "create", "init")):
        return "构建初始化"
    if any(k in name for k in ("check", "verify", "validate", "ensure")):
        return "校验判断"
    if any(k in name for k in ("run", "execute", "process", "handle")):
        return "流程执行"
    if any(k in name for k in ("get", "find", "lookup", "query")):
        return "查询获取"
    return "通用辅助"


def write_summary(data):
    funcs = data["functions"]
    files = data["files"]
    by_ext = collections.Counter(Path(f["relative"]).suffix.lower() for f in files)
    by_top = collections.Counter(top_dir(f["relative"]) for f in files)
    by_mid_funcs = collections.Counter(middle_dir(fn["relative"]) for fn in funcs)
    by_type = collections.Counter(function_type(fn) for fn in funcs)
    long_funcs = [fn for fn in funcs if fn["lines"] >= 80]
    large_funcs = sorted(funcs, key=lambda x: x["lines"], reverse=True)[:10]
    dense_files = sorted(files, key=lambda x: x["functions"], reverse=True)[:10]

    lines = []
    lines.append("# XLA 代码项目分析文字版")
    lines.append("")
    lines.append("## 1. 总体结论")
    lines.append("")
    lines.append(
        f"本次对 `{data['root']}` 做了小范围函数级扫描，共分析 {len(files)} 个代码文件，识别出 {len(funcs)} 个函数/方法。"
        "从结果看，这个项目不是简单脚本型项目，而是典型的大型系统代码库：函数数量密集，测试与核心逻辑并存，适合先通过目录、长函数和函数调用线索建立阅读地图。"
    )
    lines.append("")
    lines.append(
        f"本次识别到 {len(long_funcs)} 个超过 80 行的长函数。长函数不一定都是坏味道，但它们通常承载了较多分支、构建或测试逻辑，"
        "更适合作为后续重点阅读和重构评估入口。"
    )
    lines.append("")

    lines.append("## 2. 代码组成")
    lines.append("")
    lines.append("按文件类型看，本次扫描主要集中在：")
    lines.append("")
    for ext, count in by_ext.most_common(8):
        lines.append(f"- `{ext or '[no ext]'}`：{count} 个文件")
    lines.append("")
    lines.append("按一级目录看，代码主要分布在：")
    lines.append("")
    for name, count in by_top.most_common(8):
        lines.append(f"- `{name}`：{count} 个文件")
    lines.append("")

    lines.append("## 3. 模块阅读地图")
    lines.append("")
    lines.append("从函数数量看，优先值得关注的模块是：")
    lines.append("")
    for name, count in by_mid_funcs.most_common(10):
        lines.append(f"- `{name}`：识别到 {count} 个函数/方法，适合作为理解项目结构的入口。")
    lines.append("")

    lines.append("## 4. 函数职责分布")
    lines.append("")
    lines.append("根据函数名、注释和局部调用线索，工具把函数粗略归类为：")
    lines.append("")
    for name, count in by_type.most_common():
        lines.append(f"- {name}：{count} 个")
    lines.append("")
    lines.append("这个分布可以帮助我判断项目的阅读顺序：先看构建初始化和流程执行函数，再回到测试验证函数确认行为边界。")
    lines.append("")

    lines.append("## 5. 典型函数说明")
    lines.append("")
    for fn in large_funcs[:8]:
        purpose = fn.get("api_purpose") or fn.get("purpose") or "暂无说明"
        calls = ", ".join(fn.get("calls", [])[:5])
        lines.append(f"### `{fn['name']}`")
        lines.append("")
        lines.append(f"- 位置：`{fn['relative']}:{fn['line']}`")
        lines.append(f"- 规模：约 {fn['lines']} 行")
        lines.append(f"- 作用判断：{short(purpose, 180)}")
        if calls:
            lines.append(f"- 主要调用线索：{calls}")
        lines.append("- 阅读建议：先看函数入口参数和返回值，再看内部调用链；如果分支很多，可以拆成“输入准备 / 核心处理 / 结果校验”三段理解。")
        lines.append("")

    lines.append("## 6. 函数密集文件")
    lines.append("")
    lines.append("函数数量较多的文件适合作为模块级阅读入口，也可能是后续重构时需要拆分或补文档的对象：")
    lines.append("")
    for item in dense_files:
        if item["functions"]:
            lines.append(f"- `{item['relative']}`：{item['functions']} 个函数/方法")
    lines.append("")

    lines.append("## 7. 重构与提效建议")
    lines.append("")
    lines.append("- 先把长函数加入阅读清单，人工确认哪些是测试样例堆叠，哪些是真正的复杂业务逻辑。")
    lines.append("- 对函数密集文件补充模块说明，尤其是公共入口、构建初始化、核心流程函数。")
    lines.append("- 对测试验证类函数，可以优先提炼“覆盖了什么行为”，把它们转成理解项目行为的文档。")
    lines.append("- 后续接入 API 后，可以让大模型对重点函数生成更自然的中文解释，但默认离线分析已经足够建立第一版代码地图。")
    lines.append("")

    lines.append("## 8. 可放进参赛帖的总结")
    lines.append("")
    lines.append(
        "通过 SOLO 生成的代码分析工具，我不再只是看到“项目里有多少文件”，而是能进一步看到“哪些文件函数最密集、哪些函数最长、每个函数大概承担什么职责”。"
        "这让代码阅读从无序翻目录，变成了有入口、有优先级、有文字说明的分析流程。"
    )
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8-sig")
    print(OUT)


def main():
    write_summary(load_data())


if __name__ == "__main__":
    main()
