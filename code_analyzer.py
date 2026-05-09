#!/usr/bin/env python
"""Function-level code analyzer for local projects.

The analyzer works offline by default. Optional API summaries are enabled only
when --use-api is passed and a provider key is available in .env or the
environment.
"""

import argparse
import ast
import collections
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


CODE_EXTS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".php",
    ".py",
    ".rs",
    ".swift",
    ".ts",
    ".tsx",
}
IGNORE_DIRS = {
    ".git",
    ".hg",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".svn",
    ".venv",
    ".vscode",
    "__pycache__",
    "bazel-bin",
    "bazel-out",
    "bazel-testlogs",
    "build",
    "dist",
    "node_modules",
    "target",
    "third_party",
    "venv",
}
CONTROL_WORDS = {
    "catch",
    "for",
    "if",
    "switch",
    "while",
}
SIGNATURE_RE = re.compile(
    r"""
    (?P<prefix>(?:template\s*<[^;{}]+>\s*)?
    (?:(?:static|inline|virtual|constexpr|explicit|public|private|protected|final|override)\s+)*
    [~\w:<>,\*&\[\]\s]+\s+)
    (?P<name>[A-Za-z_~][\w:~]*)
    \s*\((?P<args>[^;{}()]*(?:\([^)]*\)[^;{}()]*)*)\)
    \s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?(?:final\s*)?
    \{
    """,
    re.VERBOSE | re.MULTILINE,
)
JS_FUNCTION_RE = re.compile(
    r"""
    (?:
      function\s+(?P<fn>[A-Za-z_$][\w$]*)\s*\((?P<fn_args>[^)]*)\)\s*\{
      |
      (?P<const>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\((?P<const_args>[^)]*)\)\s*=>\s*\{
      |
      (?P<method>[A-Za-z_$][\w$]*)\s*\((?P<method_args>[^)]*)\)\s*\{
    )
    """,
    re.VERBOSE | re.MULTILINE,
)

PROVIDER_DEFAULTS = {
    "doubao": {
        "key": "DOUBAO_API_KEY",
        "fallback_keys": ["VLM_API_KEY"],
        "base_url": "DOUBAO_BASE_URL",
        "model": "DOUBAO_MODEL",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "default_model": "doubao-seed-1-6-250615",
        "kind": "openai",
    },
    "deepseek": {
        "key": "DEEPSEEK_API_KEY",
        "fallback_keys": [],
        "base_url": "DEEPSEEK_BASE_URL",
        "model": "DEEPSEEK_MODEL",
        "default_base_url": "https://api.deepseek.com/chat/completions",
        "default_model": "deepseek-chat",
        "kind": "openai",
    },
    "chatgpt": {
        "key": "CHATGPT_API_KEY",
        "fallback_keys": ["OPENAI_API_KEY"],
        "base_url": "CHATGPT_BASE_URL",
        "model": "CHATGPT_MODEL",
        "default_base_url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o-mini",
        "kind": "openai",
    },
    "gemini": {
        "key": "GEMINI_API_KEY",
        "fallback_keys": [],
        "base_url": "GEMINI_BASE_URL",
        "model": "GEMINI_MODEL",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "default_model": "gemini-1.5-flash",
        "kind": "gemini",
    },
}


def now_stamp():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_env_file(path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def strip_json_text(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def provider_config(args):
    provider = args.provider.lower()
    defaults = PROVIDER_DEFAULTS[provider]
    api_key = os.environ.get(defaults["key"])
    for fallback in defaults["fallback_keys"]:
        api_key = api_key or os.environ.get(fallback)
    model = args.model or os.environ.get(defaults["model"]) or defaults["default_model"]
    base_url = os.environ.get(defaults["base_url"]) or defaults["default_base_url"]
    return {
        "provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "kind": defaults["kind"],
        "key_name": defaults["key"],
    }


def read_text(path, max_bytes=600_000):
    data = path.read_bytes()[:max_bytes]
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            return data.decode(enc, errors="strict")
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def compact(text, limit=140):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[: limit - 3] + "..." if len(text) > limit else text


def walk_code(root, max_files, include_vendor):
    ignored = set() if include_vendor else IGNORE_DIRS
    count = 0
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignored and not d.startswith("$")]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() not in CODE_EXTS:
                continue
            yield path
            count += 1
            if count >= max_files:
                return


def line_for_offset(text, offset):
    return text.count("\n", 0, offset) + 1


def find_matching_brace(text, open_pos):
    depth = 0
    in_string = None
    escape = False
    for idx in range(open_pos, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in {'"', "'", "`"}:
            in_string = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return idx
    return open_pos


def infer_purpose(name, doc, calls):
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", name.replace("_", " ")).lower()
    if doc:
        return compact(doc, 180)
    if name.startswith("test") or " test " in f" {words} ":
        return "测试相关逻辑，用于验证某个功能或边界条件。"
    if any(x in words for x in ("parse", "parser", "decode", "load", "read")):
        return "读取或解析输入数据，并转换成后续流程可用的结构。"
    if any(x in words for x in ("write", "save", "dump", "export", "emit")):
        return "把处理结果写出、保存或导出到外部目标。"
    if any(x in words for x in ("build", "make", "create", "init", "new")):
        return "创建、初始化或组装对象/配置/中间结果。"
    if any(x in words for x in ("check", "validate", "verify", "ensure")):
        return "执行校验逻辑，判断输入、状态或约束是否满足要求。"
    if any(x in words for x in ("run", "execute", "process", "handle")):
        return "执行主要处理流程，协调若干步骤完成任务。"
    if any(x in words for x in ("get", "find", "lookup", "query", "select")):
        return "查询、定位或返回某类数据。"
    if calls:
        return f"围绕 {', '.join(calls[:3])} 等调用组织逻辑，建议结合调用关系继续阅读。"
    return "根据函数名和局部结构推断，这是一个项目内部辅助函数，建议结合调用方确认业务语义。"


def collect_python_calls(node):
    calls = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name):
                calls.append(func.id)
            elif isinstance(func, ast.Attribute):
                calls.append(func.attr)
    return list(dict.fromkeys(calls))[:12]


def analyze_python(path, text, rel):
    results = []
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], [{"path": str(path), "issue": f"Python 语法解析失败：{exc}"}]

    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        owner = None
        parent = parents.get(node)
        if isinstance(parent, ast.ClassDef):
            owner = parent.name
        args = [a.arg for a in node.args.args]
        calls = collect_python_calls(node)
        doc = ast.get_docstring(node) or ""
        name = f"{owner}.{node.name}" if owner else node.name
        end_line = getattr(node, "end_lineno", node.lineno)
        results.append(
            {
                "name": name,
                "kind": "async function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                "path": str(path),
                "relative": rel,
                "line": node.lineno,
                "end_line": end_line,
                "lines": max(1, end_line - node.lineno + 1),
                "args": args,
                "calls": calls,
                "doc": compact(doc, 240),
                "purpose": infer_purpose(node.name, doc, calls),
                "snippet": "\n".join(text.splitlines()[node.lineno - 1 : min(end_line, node.lineno + 80)]),
            }
        )
    return results, []


def comment_above(lines, line_no):
    comments = []
    idx = line_no - 2
    while idx >= 0 and len(comments) < 6:
        stripped = lines[idx].strip()
        if not stripped:
            if comments:
                break
            idx -= 1
            continue
        if stripped.startswith(("//", "#", "*", "/*")):
            comments.append(stripped.strip("/*# "))
            idx -= 1
            continue
        break
    return " ".join(reversed(comments))


def analyze_c_like(path, text, rel):
    results = []
    lines = text.splitlines()
    regex = JS_FUNCTION_RE if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"} else SIGNATURE_RE
    for match in regex.finditer(text):
        if regex is JS_FUNCTION_RE:
            name = match.group("fn") or match.group("const") or match.group("method")
            args_text = match.group("fn_args") or match.group("const_args") or match.group("method_args") or ""
        else:
            name = match.group("name")
            args_text = match.group("args") or ""
            if name.split("::")[-1] in CONTROL_WORDS:
                continue
        open_brace = text.find("{", match.start(), match.end() + 5)
        close_brace = find_matching_brace(text, open_brace)
        line = line_for_offset(text, match.start())
        end_line = line_for_offset(text, close_brace)
        if end_line < line:
            continue
        args = [compact(a.strip(), 60) for a in args_text.split(",") if a.strip()]
        local_text = text[match.start() : min(close_brace + 1, match.start() + 6000)]
        calls = re.findall(r"\b([A-Za-z_][\w:]*)\s*\(", local_text)
        calls = [c.split("::")[-1] for c in calls if c.split("::")[-1] not in CONTROL_WORDS and c != name]
        calls = list(dict.fromkeys(calls))[:12]
        doc = comment_above(lines, line)
        results.append(
            {
                "name": name,
                "kind": "function",
                "path": str(path),
                "relative": rel,
                "line": line,
                "end_line": end_line,
                "lines": max(1, end_line - line + 1),
                "args": args,
                "calls": calls,
                "doc": compact(doc, 240),
                "purpose": infer_purpose(name.split("::")[-1], doc, calls),
                "snippet": "\n".join(lines[line - 1 : min(end_line, line + 80)]),
            }
        )
    return results, []


def analyze_file(path, root):
    rel = str(path.relative_to(root))
    text = read_text(path)
    if path.suffix.lower() == ".py":
        return analyze_python(path, text, rel)
    return analyze_c_like(path, text, rel)


def api_summarize(functions, args):
    config = provider_config(args)
    if not config["api_key"]:
        return [f"未设置 {config['key_name']}，已跳过 {config['provider']} API 总结。"]

    errors = []
    for item in functions[: args.api_limit]:
        prompt = (
            "你是资深代码审查助手。请用中文用 1 句话解释这个函数的作用，"
            "再给 1 条阅读或重构建议。只返回 JSON，字段为 purpose 和 suggestion。\n\n"
            f"文件：{item['relative']}:{item['line']}\n"
            f"函数：{item['name']}\n"
            f"代码：\n{item['snippet'][:3500]}"
        )
        try:
            if config["kind"] == "gemini":
                parsed = call_gemini(config, prompt, args.api_timeout)
            else:
                parsed = call_openai_compatible(config, prompt, args.api_timeout)
            item["api_purpose"] = compact(parsed.get("purpose", ""), 240)
            item["api_suggestion"] = compact(parsed.get("suggestion", ""), 240)
            item["api_provider"] = config["provider"]
            item["api_model"] = config["model"]
        except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError, ValueError) as exc:
            errors.append(f"{item['relative']}:{item['line']} {config['provider']} API 总结失败：{exc}")
    return errors


def call_openai_compatible(config, prompt, timeout):
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": "你只输出紧凑 JSON，不输出 Markdown。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        config["base_url"],
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {config['api_key']}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    return json.loads(strip_json_text(content))


def call_gemini(config, prompt, timeout):
    base_url = config["base_url"].format(model=config["model"])
    sep = "&" if "?" in base_url else "?"
    url = f"{base_url}{sep}key={config['api_key']}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": "你只输出紧凑 JSON，不输出 Markdown。\n\n" + prompt,
                    }
                ],
            }
        ],
        "generationConfig": {"temperature": 0.2},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(strip_json_text(content))


def analyze_project(args):
    root = Path(args.root).resolve()
    functions = []
    issues = []
    files = []
    for path in walk_code(root, args.max_files, args.include_vendor):
        try:
            found, file_issues = analyze_file(path, root)
        except Exception as exc:
            found, file_issues = [], [{"path": str(path), "issue": f"分析失败：{exc}"}]
        files.append({"path": str(path), "relative": str(path.relative_to(root)), "functions": len(found)})
        functions.extend(found)
        issues.extend(file_issues)

    functions.sort(key=lambda x: (x["relative"], x["line"]))
    if args.use_api:
        issues.extend(api_summarize(functions, args))
    return {"root": str(root), "generated_at": now_stamp(), "files": files, "functions": functions, "issues": issues}


def write_json(data, path):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8-sig")


def write_report(data, path):
    funcs = data["functions"]
    files = data["files"]
    by_ext = collections.Counter(Path(f["path"]).suffix.lower() for f in files)
    by_dir = collections.Counter(str(Path(f["relative"]).parent).split(os.sep)[0] for f in files)
    biggest = sorted(funcs, key=lambda x: x["lines"], reverse=True)[:15]
    dense_files = sorted(files, key=lambda x: x["functions"], reverse=True)[:15]

    lines = []
    lines.append("# 代码项目函数级分析报告")
    lines.append("")
    lines.append(f"- 生成时间：{data['generated_at']}")
    lines.append(f"- 项目目录：{data['root']}")
    lines.append(f"- 分析代码文件：{len(files)}")
    lines.append(f"- 识别函数/方法：{len(funcs)}")
    lines.append(f"- 解析提示：{len(data['issues'])}")
    lines.append("")

    lines.append("## 1. 文件类型")
    lines.append("")
    for ext, count in by_ext.most_common(12):
        lines.append(f"- `{ext or '[no ext]'}`: {count}")
    lines.append("")

    lines.append("## 2. 主要目录")
    lines.append("")
    for name, count in by_dir.most_common(12):
        lines.append(f"- `{name}`: {count} 个代码文件")
    lines.append("")

    lines.append("## 3. 函数最多的文件")
    lines.append("")
    for item in dense_files:
        if item["functions"]:
            lines.append(f"- `{item['relative']}`: {item['functions']} 个函数/方法")
    lines.append("")

    lines.append("## 4. 较长函数提醒")
    lines.append("")
    for fn in biggest:
        lines.append(f"- `{fn['relative']}:{fn['line']}` `{fn['name']}`，约 {fn['lines']} 行")
    lines.append("")

    lines.append("## 5. 函数作用清单")
    lines.append("")
    for fn in funcs[:120]:
        purpose = fn.get("api_purpose") or fn["purpose"]
        suggestion = fn.get("api_suggestion")
        args = ", ".join(fn["args"][:6])
        calls = ", ".join(fn["calls"][:6])
        lines.append(f"### `{fn['name']}`")
        lines.append("")
        lines.append(f"- 位置：`{fn['relative']}:{fn['line']}`")
        lines.append(f"- 参数：{args or '无明显参数'}")
        lines.append(f"- 作用：{purpose}")
        if calls:
            lines.append(f"- 主要调用：{calls}")
        if suggestion:
            lines.append(f"- API 建议：{suggestion}")
        lines.append("")

    if data["issues"]:
        lines.append("## 6. 解析提示")
        lines.append("")
        for item in data["issues"][:40]:
            if isinstance(item, str):
                lines.append(f"- {item}")
            else:
                lines.append(f"- `{item.get('path', '')}` {item.get('issue', '')}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8-sig")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Analyze functions in a local code project.")
    parser.add_argument("root", help="Code project directory")
    parser.add_argument("--out", type=Path, default=Path("code_analysis_report.md"))
    parser.add_argument("--json-out", type=Path, default=Path("code_analysis_index.json"))
    parser.add_argument("--max-files", type=int, default=800)
    parser.add_argument("--include-vendor", action="store_true")
    parser.add_argument("--use-api", action="store_true", help="Use selected model API for summaries")
    parser.add_argument(
        "--provider",
        choices=sorted(PROVIDER_DEFAULTS),
        default=os.environ.get("MODEL_PROVIDER", "doubao"),
        help="Model provider to read from .env",
    )
    parser.add_argument("--api-limit", type=int, default=20, help="Max functions to summarize by API")
    parser.add_argument("--api-timeout", type=int, default=30)
    parser.add_argument("--model", default=None, help="Override provider model from .env")
    return parser.parse_args(argv)


def main(argv=None):
    load_env_file(Path(__file__).resolve().parent / ".env")
    args = parse_args(argv or sys.argv[1:])
    data = analyze_project(args)
    write_json(data, args.json_out)
    write_report(data, args.out)
    print(f"Analyzed {len(data['files'])} files")
    print(f"Found {len(data['functions'])} functions")
    print(f"Report: {args.out.resolve()}")
    print(f"Index:  {args.json_out.resolve()}")


if __name__ == "__main__":
    main()
