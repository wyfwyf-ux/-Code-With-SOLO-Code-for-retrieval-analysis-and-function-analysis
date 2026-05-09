#!/usr/bin/env python
"""Local web server for Self Help Assistant.

This server only binds to localhost. It lets the HTML page run the existing
Python scanners and return report summaries to the browser.
"""

import argparse
import collections
import json
import subprocess
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote


BASE = Path(__file__).resolve().parent
IGNORE_DIRS = {
    ".cache",
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


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_text(path, limit=5000):
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    return text[:limit]


def run_command(args, timeout=180):
    proc = subprocess.run(
        args,
        cwd=str(BASE),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "命令执行失败").strip())
    return proc.stdout.strip()


def unique_name(prefix, suffix):
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return BASE / f"{prefix}_{stamp}{suffix}"


def default_search_roots():
    desktop_candidates = [Path("F:/Desktop"), Path.home() / "Desktop"]
    candidates = []
    for desktop in desktop_candidates:
        if desktop.exists():
            candidates.extend([p for p in sorted(desktop.iterdir()) if p.is_dir()])
            candidates.append(desktop)
    candidates.extend([Path.home() / "Documents", BASE])
    roots = []
    seen = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if resolved.exists() and key not in seen:
            roots.append(resolved)
            seen.add(key)
    return roots or [BASE]


def find_by_filename(roots, keywords, max_visited=120000, max_hits=50):
    if not keywords:
        return []
    lowered = [k.lower() for k in keywords if k]
    hits = []
    seen = set()
    visited = 0
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os_walk_sorted(root):
            visited += len(filenames)
            for filename in filenames:
                name = filename.lower()
                matched = [k for k in lowered if k in name]
                if not matched:
                    continue
                path = str(Path(dirpath) / filename)
                key = path.lower()
                if key in seen:
                    continue
                seen.add(key)
                hits.append({"path": path, "keywords": matched, "preview": "文件名匹配"})
                if len(hits) >= max_hits:
                    return hits
            if visited >= max_visited:
                return hits
    return hits


def summarize_file(path):
    if not path.exists() or not path.is_file():
        return ""
    ext = path.suffix.lower()
    try:
        if ext in {".txt", ".md", ".py", ".js", ".ts", ".java", ".cpp", ".cc", ".h", ".hpp", ".json", ".yaml", ".yml", ".csv"}:
            data = path.read_bytes()[:12000]
            decoded = ""
            for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
                try:
                    decoded = data.decode(enc)
                    break
                except UnicodeDecodeError:
                    pass
            return " ".join(decoded.split())[:420]
        if ext in {".docx", ".pptx"}:
            import zipfile
            from xml.etree import ElementTree

            prefix = "word/" if ext == ".docx" else "ppt/slides/slide"
            chunks = []
            with zipfile.ZipFile(path) as zf:
                names = sorted(n for n in zf.namelist() if n.startswith(prefix) and n.endswith(".xml"))
                for name in names[:8]:
                    root = ElementTree.fromstring(zf.read(name))
                    for node in root.iter():
                        if node.tag.endswith("}t") and node.text:
                            chunks.append(node.text)
                            if sum(len(x) for x in chunks) > 650:
                                return " ".join(chunks)[:420]
            return " ".join(chunks)[:420]
    except Exception:
        return ""
    if ext == ".pdf":
        return "PDF 文件：已定位路径，当前轻量模式不解析全文。"
    if ext in {".mp4", ".mov", ".avi", ".mkv"}:
        return "视频素材：已定位路径，可根据文件名和所在目录判断用途。"
    return "已定位文件路径，当前类型暂不提取内容。"


def os_walk_sorted(root):
    import os

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS and not d.startswith("$"))
        filenames.sort()
        yield dirpath, dirnames, filenames


def analyze_search(payload):
    paths = [p.strip() for p in payload.get("paths", []) if p.strip()]
    keywords = [k.strip() for k in payload.get("keywords", []) if k.strip()]
    max_files = str(payload.get("max_files") or 2500)
    report = unique_name("文件查找报告", ".md")
    index = unique_name("文件查找索引", ".json")

    cmd = [sys.executable, "self_help_assistant.py", *paths]
    for keyword in keywords:
        cmd.extend(["--name", keyword, "--query", keyword])
    cmd.extend(["--out", str(report), "--json-out", str(index), "--max-files", max_files])
    output = run_command(cmd)

    data = read_json(index)
    hits = data.get("keyword_hits", [])
    items = data.get("items", [])
    locations = [
        {
            "path": hit.get("path", ""),
            "keywords": hit.get("keywords", []),
            "preview": hit.get("preview", "") or summarize_file(Path(hit.get("path", ""))),
        }
        for hit in hits[:30]
    ]
    fast_roots = [Path(p) for p in paths] if paths else default_search_roots()
    known_paths = {item["path"].lower() for item in locations}
    for item in find_by_filename(fast_roots, keywords):
        if item["path"].lower() not in known_paths:
            item["preview"] = summarize_file(Path(item["path"])) or item.get("preview", "")
            locations.append(item)
            known_paths.add(item["path"].lower())
        if len(locations) >= 30:
            break
    if not locations and keywords:
        lowered = [k.lower() for k in keywords]
        for item in items:
            name = item.get("name", "").lower()
            if any(k in name for k in lowered):
                path = item.get("path", "")
                locations.append({"path": path, "keywords": keywords, "preview": item.get("preview", "") or summarize_file(Path(path))})
                if len(locations) >= 30:
                    break

    analysis_text = build_search_analysis(keywords, locations, items)

    return {
        "mode": "search",
        "title": "文件查找结果",
        "summary": f"扫描 {len(items)} 个文件，命中 {len(locations)} 条与 {', '.join(keywords) or '目录总览'} 相关的线索。",
        "detail": "下面是匹配到的文件位置。报告中还包含最近修改、大文件提醒、文件类型分布等内容。",
        "analysis_text": analysis_text,
        "metrics": [
            [str(len(items)), "扫描文件"],
            [str(len([i for i in items if i.get("category") == "document"])), "文档文件"],
            [str(len(locations)), "命中位置"],
            [str(len([i for i in items if i.get("category") == "video"])), "视频素材"],
        ],
        "locations": locations,
        "artifacts": [
            [report.name, "Markdown 文件查找报告"],
            [index.name, "结构化 JSON 索引"],
        ],
        "command": " ".join(cmd),
        "stdout": output,
        "report_excerpt": read_text(report, 3000),
        "image": "assets/04_document_keyword_hits.png",
        "secondary_image": "assets/05_large_files.png",
    }


def build_search_analysis(keywords, locations, items):
    lines = []
    query = "、".join(keywords) if keywords else "目录总览"
    lines.append(f"【文档查找总结】")
    lines.append(f"本次围绕「{query}」进行查找，共扫描 {len(items)} 个文件，找到 {len(locations)} 条相关线索。")
    lines.append("")
    if not locations:
        lines.append("没有找到明确匹配的文件。建议缩短关键词，或者填写更具体的搜索范围后再试。")
        return "\n".join(lines)

    best = locations[0]
    best_path = best.get("path", "")
    best_preview = best.get("preview", "")
    lines.append("最可能需要打开的文件：")
    lines.append(best_path)
    lines.append("")
    lines.append("这个文件的大致内容：")
    lines.append(best_preview or "已定位文件路径，但当前类型暂时无法提取内容摘要。")
    lines.append("")
    if len(locations) > 1:
        lines.append("其他相关文件：")
        for item in locations[1:6]:
            lines.append(f"- {item.get('path', '')}")
    lines.append("")
    lines.append("建议下一步：先打开最相关文件确认内容；如果不是目标文件，可以点击左侧其他结果逐个查看摘要。")
    return "\n".join(lines)


def analyze_code(payload):
    paths = [p.strip() for p in payload.get("paths", []) if p.strip()]
    if not paths:
        raise ValueError("代码分析需要输入一个代码项目文件夹。")
    root = paths[0]
    provider = payload.get("provider") or "offline"
    max_files = str(payload.get("max_files") or 80)
    report = unique_name("代码函数分析报告", ".md")
    index = BASE / "code_analysis_index.json"

    cmd = [sys.executable, "code_analyzer.py", root, "--max-files", max_files, "--out", str(report), "--json-out", str(index)]
    if provider != "offline":
        cmd.extend(["--use-api", "--provider", provider, "--api-limit", "10"])
    output = run_command(cmd, timeout=240)
    summary_output = run_command([sys.executable, "code_analysis_text_summary.py"], timeout=60)
    run_command([sys.executable, "visualize_code_analysis.py"], timeout=60)

    data = read_json(index)
    funcs = data.get("functions", [])
    files = data.get("files", [])
    long_funcs = [fn for fn in funcs if int(fn.get("lines", 0)) >= 80]
    top_functions = [
        {
            "name": fn.get("name", ""),
            "path": f"{fn.get('relative', '')}:{fn.get('line', '')}",
            "purpose": fn.get("api_purpose") or fn.get("purpose", ""),
            "lines": fn.get("lines", 0),
        }
        for fn in sorted(funcs, key=lambda x: int(x.get("lines", 0)), reverse=True)[:12]
    ]
    packages = build_packages(files, funcs)

    text_summary = BASE / "xla_代码分析文字版.md"
    code_analysis_text = build_code_analysis(provider, packages, files, funcs, long_funcs)
    return {
        "mode": "code",
        "title": "代码分析结果",
        "summary": f"分析 {len(files)} 个代码文件，识别 {len(funcs)} 个函数/方法，发现 {len(long_funcs)} 个长函数。",
        "detail": f"当前模型模式：{provider}。结果包含函数清单、函数作用、模块阅读地图和重构建议。",
        "analysis_text": code_analysis_text,
        "metrics": [
            [str(len(files)), "代码文件"],
            [str(len(funcs)), "函数/方法"],
            [str(len(long_funcs)), "长函数"],
            [str(len(data.get("issues", []))), "解析提示"],
        ],
        "functions": top_functions,
        "packages": packages,
        "artifacts": [
            [report.name, "函数级 Markdown 报告"],
            [index.name, "函数结构化 JSON 索引"],
            [text_summary.name, "代码分析文字版总结"],
        ],
        "command": " ".join(cmd),
        "stdout": output + "\n" + summary_output,
        "report_excerpt": read_text(text_summary, 3000) if text_summary.exists() else read_text(report, 3000),
        "image": "assets/07_function_purpose_cards.png",
        "secondary_image": "assets/06_code_analysis_overview.png",
    }


def build_code_analysis(provider, packages, files, funcs, long_funcs):
    lines = []
    lines.append("【代码项目总结】")
    lines.append(f"本次使用 {provider} 模式分析项目，共扫描 {len(files)} 个代码文件，识别 {len(funcs)} 个函数/方法。")
    lines.append(f"其中长函数 {len(long_funcs)} 个，适合作为后续重点阅读对象。")
    lines.append("")
    if packages:
        lines.append("优先阅读的包/模块：")
        for pkg in packages[:5]:
            lines.append(f"- {pkg['name']}：{pkg['purpose']}（{pkg['file_count']} 个文件，{pkg['function_count']} 个函数）")
    lines.append("")
    lines.append("建议下一步：先点击左侧函数数量较多的包，理解它的职责，再进入右侧函数列表查看核心函数作用。")
    return "\n".join(lines)


def package_name(relative):
    parts = Path(relative).parts
    if not parts:
        return "."
    if len(parts) == 1:
        return parts[0]
    return "/".join(parts[:2])


def infer_package_purpose(name, functions):
    lower = name.lower()
    fn_names = " ".join(fn.get("name", "").lower() for fn in functions[:80])
    text = f"{lower} {fn_names}"
    if any(k in text for k in ["build", "configure", "flag", "option", "bazel"]):
        return "构建配置和运行参数模块，负责组装选项、配置环境或生成规则。"
    if "test" in text:
        return "测试验证相关模块，用于确认核心行为、边界条件和兼容性。"
    if any(k in text for k in ["literal", "shape", "layout", "array"]):
        return "数据结构和基础表示模块，负责描述数据形状、布局或字面量内容。"
    if any(k in text for k in ["gpu", "cuda", "stream", "buffer"]):
        return "后端执行或设备资源模块，涉及 GPU、流、缓冲区等运行时能力。"
    if any(k in text for k in ["parse", "parser", "hlo", "mlir"]):
        return "编译 IR、解析或转换相关模块，适合从入口函数和测试用例开始阅读。"
    return "项目内部功能模块，可先看高频函数和较长函数建立阅读入口。"


def build_packages(files, funcs):
    by_pkg_files = collections.defaultdict(list)
    by_pkg_funcs = collections.defaultdict(list)
    for item in files:
        by_pkg_files[package_name(item.get("relative", ""))].append(item)
    for fn in funcs:
        by_pkg_funcs[package_name(fn.get("relative", ""))].append(fn)

    packages = []
    for name in sorted(set(by_pkg_files) | set(by_pkg_funcs)):
        fns = sorted(by_pkg_funcs[name], key=lambda x: int(x.get("lines", 0)), reverse=True)
        packages.append(
            {
                "name": name,
                "file_count": len(by_pkg_files[name]),
                "function_count": len(fns),
                "purpose": infer_package_purpose(name, fns),
                "functions": [
                    {
                        "name": fn.get("name", ""),
                        "path": f"{fn.get('relative', '')}:{fn.get('line', '')}",
                        "purpose": fn.get("api_purpose") or fn.get("purpose", ""),
                        "lines": fn.get("lines", 0),
                    }
                    for fn in fns[:40]
                ],
            }
        )
    packages.sort(key=lambda x: x["function_count"], reverse=True)
    return packages[:30]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE), **kwargs)

    def log_message(self, format, *args):
        return

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def guess_type(self, path):
        content_type = super().guess_type(path)
        if path.endswith(".html"):
            return "text/html; charset=utf-8"
        if path.endswith(".js"):
            return "application/javascript; charset=utf-8"
        if path.endswith(".css"):
            return "text/css; charset=utf-8"
        return content_type

    def do_GET(self):
        if self.path in {"/", ""}:
            self.path = "/3D%E6%A1%8C%E9%9D%A2%E5%B1%95%E7%A4%BA.html"
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/analyze":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            mode = payload.get("mode")
            if mode == "search":
                result = analyze_search(payload)
            elif mode == "code":
                result = analyze_code(payload)
            else:
                raise ValueError("未知任务类型。")
            self.send_json({"ok": True, "result": result})
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=500)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Self Help Assistant running at http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
