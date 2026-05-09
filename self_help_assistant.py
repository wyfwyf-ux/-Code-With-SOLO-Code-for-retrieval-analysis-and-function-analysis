#!/usr/bin/env python
"""
Self Help Assistant

Local scanner for personal documents and code projects. It builds a lightweight
index and a Markdown report without uploading files anywhere.
"""

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree


DOC_EXTS = {
    ".doc",
    ".docx",
    ".md",
    ".pdf",
    ".ppt",
    ".pptx",
    ".txt",
    ".xls",
    ".xlsx",
    ".csv",
}
CODE_EXTS = {
    ".bat",
    ".bazel",
    ".bzl",
    ".c",
    ".cc",
    ".cmd",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".lua",
    ".m",
    ".mlir",
    ".mm",
    ".php",
    ".proto",
    ".py",
    ".rs",
    ".sh",
    ".sql",
    ".swift",
    ".td",
    ".toml",
    ".ts",
    ".tsx",
    ".xml",
    ".yaml",
    ".yml",
}
TEXT_EXTS = DOC_EXTS | CODE_EXTS | {".rst", ".log", ".ini", ".cfg"}
DEFAULT_IGNORE_DIRS = {
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
TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b[:：]?\s*(.*)", re.IGNORECASE)


def now_stamp():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_rel(path, root):
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def sha1_short(text):
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:10]


def classify_file(path):
    ext = path.suffix.lower()
    if ext in DOC_EXTS:
        return "document"
    if ext in CODE_EXTS or path.name in {"BUILD", "WORKSPACE", "Makefile", "Dockerfile"}:
        return "code"
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}:
        return "image"
    if ext in {".mp4", ".mov", ".avi", ".mkv"}:
        return "video"
    if ext in {".zip", ".rar", ".7z", ".tar", ".gz"}:
        return "archive"
    return "other"


def read_text_file(path, max_chars):
    data = path.read_bytes()[: max_chars * 4]
    for encoding in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            return data.decode(encoding, errors="strict")[:max_chars]
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")[:max_chars]


def read_docx_text(path, max_chars):
    chunks = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.startswith("word/") and n.endswith(".xml")]
            for name in names[:8]:
                xml = zf.read(name)
                root = ElementTree.fromstring(xml)
                for node in root.iter():
                    if node.tag.endswith("}t") and node.text:
                        chunks.append(node.text)
                        if sum(len(x) for x in chunks) >= max_chars:
                            return " ".join(chunks)[:max_chars]
    except Exception:
        return ""
    return " ".join(chunks)[:max_chars]


def read_pptx_text(path, max_chars):
    chunks = []
    try:
        with zipfile.ZipFile(path) as zf:
            slide_names = sorted(
                n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")
            )
            for name in slide_names[:20]:
                xml = zf.read(name)
                root = ElementTree.fromstring(xml)
                for node in root.iter():
                    if node.tag.endswith("}t") and node.text:
                        chunks.append(node.text)
                        if sum(len(x) for x in chunks) >= max_chars:
                            return " ".join(chunks)[:max_chars]
    except Exception:
        return ""
    return " ".join(chunks)[:max_chars]


def extract_sample(path, max_chars):
    ext = path.suffix.lower()
    if ext == ".docx":
        return read_docx_text(path, max_chars)
    if ext == ".pptx":
        return read_pptx_text(path, max_chars)
    if ext in TEXT_EXTS or path.name in {"BUILD", "WORKSPACE", "Makefile", "Dockerfile"}:
        if path.stat().st_size > 20 * 1024 * 1024:
            return ""
        try:
            return read_text_file(path, max_chars)
        except Exception:
            return ""
    return ""


def walk_files(roots, max_files, include_vendor):
    seen = set()
    ignored = set() if include_vendor else DEFAULT_IGNORE_DIRS
    for root in roots:
        root_count = 0
        root = root.resolve()
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ignored and not d.startswith("$")]
            for filename in filenames:
                path = Path(dirpath) / filename
                key = str(path).lower()
                if key in seen:
                    continue
                seen.add(key)
                root_count += 1
                yield root, path
                if root_count >= max_files:
                    break
            if root_count >= max_files:
                break


def scan(roots, args):
    items = []
    todo_hits = []
    keyword_hits = []
    keywords = [k.strip().lower() for k in args.query if k.strip()]
    name_keywords = [k.strip().lower() for k in args.name if k.strip()]

    for root, path in walk_files(roots, args.max_files, args.include_vendor):
        try:
            stat = path.stat()
        except OSError:
            continue

        category = classify_file(path)
        sample = ""
        if category in {"document", "code"} or path.suffix.lower() in TEXT_EXTS:
            sample = extract_sample(path, args.sample_chars)

        file_name = path.name.lower()
        text_for_search = f"{path.name}\n{sample}".lower()
        hit_words = [k for k in keywords if k in text_for_search]
        hit_words.extend(k for k in name_keywords if k in file_name)
        if hit_words:
            keyword_hits.append(
                {
                    "path": str(path),
                    "root": str(root),
                    "keywords": list(dict.fromkeys(hit_words)),
                    "preview": compact(sample, 160),
                }
            )

        if sample and category == "code":
            for idx, line in enumerate(sample.splitlines(), start=1):
                match = TODO_RE.search(line)
                if match:
                    todo_hits.append(
                        {
                            "path": str(path),
                            "line": idx,
                            "kind": match.group(1).upper(),
                            "text": compact(match.group(2), 120),
                        }
                    )

        items.append(
            {
                "path": str(path),
                "root": str(root),
                "relative": safe_rel(path, root),
                "name": path.name,
                "ext": path.suffix.lower() or "[no ext]",
                "category": category,
                "size": stat.st_size,
                "modified": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "sample_id": sha1_short(sample) if sample else "",
                "preview": compact(sample, 220),
            }
        )

    return {"items": items, "todo_hits": todo_hits, "keyword_hits": keyword_hits}


def compact(text, limit):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[: limit - 3] + "..." if len(text) > limit else text


def human_size(num):
    units = ["B", "KB", "MB", "GB"]
    size = float(num)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024


def write_report(result, roots, args):
    items = result["items"]
    by_category = collections.Counter(i["category"] for i in items)
    by_ext = collections.Counter(i["ext"] for i in items)
    by_root = collections.Counter(i["root"] for i in items)
    duplicate_names = {
        name: paths
        for name, paths in group_by_name(items).items()
        if len(paths) >= 2 and name.lower() not in {"readme.md", "license"}
    }
    recent = sorted(items, key=lambda x: x["modified"], reverse=True)[:12]
    large = sorted(items, key=lambda x: x["size"], reverse=True)[:12]
    docs = [i for i in items if i["category"] == "document"]
    code = [i for i in items if i["category"] == "code"]

    lines = []
    lines.append("# 自我帮助小助手扫描报告")
    lines.append("")
    lines.append(f"- 生成时间：{now_stamp()}")
    lines.append(f"- 扫描根目录：{', '.join(str(r) for r in roots)}")
    lines.append(f"- 扫描文件数：{len(items)}")
    lines.append(f"- 文档文件：{len(docs)}")
    lines.append(f"- 代码文件：{len(code)}")
    lines.append(f"- TODO/FIXME/HACK 命中：{len(result['todo_hits'])}")
    lines.append(f"- 关键词命中：{len(result['keyword_hits'])}")
    lines.append("")

    lines.append("## 1. 文件分类总览")
    lines.append("")
    for category, count in by_category.most_common():
        lines.append(f"- {category}: {count}")
    lines.append("")

    lines.append("## 2. 根目录分布")
    lines.append("")
    for root, count in by_root.most_common():
        lines.append(f"- `{root}`: {count}")
    lines.append("")

    lines.append("## 3. 主要文件类型")
    lines.append("")
    for ext, count in by_ext.most_common(15):
        lines.append(f"- `{ext}`: {count}")
    lines.append("")

    lines.append("## 4. 最近修改的文件")
    lines.append("")
    for item in recent:
        lines.append(f"- `{item['modified']}` `{item['category']}` {item['path']}")
    lines.append("")

    lines.append("## 5. 大文件提醒")
    lines.append("")
    for item in large:
        lines.append(f"- {human_size(item['size'])} `{item['category']}` {item['path']}")
    lines.append("")

    if result["keyword_hits"]:
        lines.append("## 6. 关键词命中")
        lines.append("")
        for hit in result["keyword_hits"][:30]:
            lines.append(f"- {', '.join(hit['keywords'])}: {hit['path']}")
            if hit["preview"]:
                lines.append(f"  - 摘要：{hit['preview']}")
        lines.append("")

    if result["todo_hits"]:
        lines.append("## 7. 代码待办与风险标记")
        lines.append("")
        for hit in result["todo_hits"][:40]:
            lines.append(f"- `{hit['kind']}` {hit['path']}:{hit['line']} {hit['text']}")
        lines.append("")

    lines.append("## 8. 可能重复的文件名")
    lines.append("")
    if duplicate_names:
        for name, paths in list(duplicate_names.items())[:20]:
            lines.append(f"- `{name}`")
            for path in paths[:5]:
                lines.append(f"  - {path}")
    else:
        lines.append("- 暂未发现明显重复文件名。")
    lines.append("")

    lines.append("## 9. 可复用 Prompt")
    lines.append("")
    lines.append("```text")
    lines.append("请基于这份扫描报告，帮我按“重要程度 / 所属项目 / 下一步动作”整理待处理资料，")
    lines.append("并输出一个 1 周内可执行的清理计划。每个建议都要引用具体文件路径。")
    lines.append("```")
    lines.append("")

    args.out.write_text("\n".join(lines), encoding="utf-8-sig")


def group_by_name(items):
    groups = collections.defaultdict(list)
    for item in items:
        groups[item["name"]].append(item["path"])
    return groups


def default_roots():
    desktop_candidates = [Path("F:/Desktop"), Path.home() / "Desktop"]
    candidates = []
    for desktop in desktop_candidates:
        if desktop.exists():
            candidates.extend([p for p in sorted(desktop.iterdir()) if p.is_dir()])
            candidates.append(desktop)
    candidates.extend([Path.home() / "Documents", Path.cwd()])
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
    return roots or [Path.cwd()]


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Scan personal documents and code projects locally.")
    parser.add_argument("roots", nargs="*", help="Directories to scan, for example F:\\Desktop\\xla")
    parser.add_argument("--out", type=Path, default=Path("self_help_report.md"), help="Markdown report path")
    parser.add_argument("--json-out", type=Path, default=Path("self_help_index.json"), help="JSON index path")
    parser.add_argument("--query", action="append", default=[], help="Keyword to search. Can be repeated.")
    parser.add_argument("--name", action="append", default=[], help="File name keyword to search. Can be repeated.")
    parser.add_argument("--max-files", type=int, default=3000, help="Maximum files to scan per root")
    parser.add_argument("--sample-chars", type=int, default=8000, help="Text sample size per readable file")
    parser.add_argument("--include-vendor", action="store_true", help="Include vendor/build directories")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    roots = [Path(r) for r in args.roots] if args.roots else default_roots()
    result = scan(roots, args)
    payload = {
        "generated_at": now_stamp(),
        "roots": [str(r) for r in roots],
        **result,
    }
    args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    write_report(result, roots, args)
    print(f"Scanned {len(result['items'])} files")
    print(f"Report: {args.out.resolve()}")
    print(f"Index:  {args.json_out.resolve()}")


if __name__ == "__main__":
    main()
