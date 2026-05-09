#!/usr/bin/env python
"""Generate image assets for the Self Help Assistant report."""

import collections
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE = Path(__file__).resolve().parent
INDEX = BASE / "xla_研二下_自我帮助索引.json"
OUT = BASE / "assets"

W, H = 1400, 900
BG = "#f7f4ee"
INK = "#1f2933"
MUTED = "#61707d"
GRID = "#d8d2c6"
CARD = "#fffdf8"
RED = "#c84c3d"
BLUE = "#2f6f9f"
GREEN = "#4f8a5b"
GOLD = "#b8872f"
VIOLET = "#7a5fa8"
CYAN = "#377d83"
PALETTE = [BLUE, GREEN, GOLD, RED, VIOLET, CYAN, "#8f6b4a", "#5d6f80"]


def font(size, bold=False):
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for item in candidates:
        path = Path(item)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


F_TITLE = font(48, True)
F_H2 = font(30, True)
F_BODY = font(24)
F_SMALL = font(19)
F_TINY = font(16)


def load_data():
    text = INDEX.read_text(encoding="utf-8-sig")
    return json.loads(text)


def save(img, name):
    OUT.mkdir(exist_ok=True)
    path = OUT / name
    img.save(path)
    return path


def canvas(title, subtitle):
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.text((70, 52), title, fill=INK, font=F_TITLE)
    draw.text((74, 116), subtitle, fill=MUTED, font=F_BODY)
    draw.line((70, 165, W - 70, 165), fill=GRID, width=2)
    return img, draw


def rounded(draw, box, fill=CARD, outline="#e3ddd2", radius=18, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def human_size(num):
    units = ["B", "KB", "MB", "GB"]
    size = float(num)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024


def summary_card(data):
    items = data["items"]
    cats = collections.Counter(i["category"] for i in items)
    todos = len(data["todo_hits"])
    keywords = len(data["keyword_hits"])
    roots = collections.Counter(i["root"] for i in items)

    img, draw = canvas("自我帮助小助手：扫描总览", "代码项目 + 个人文档，一条命令生成资料地图")
    metrics = [
        ("扫描文件", str(len(items)), BLUE),
        ("代码文件", str(cats["code"]), GREEN),
        ("文档文件", str(cats["document"]), GOLD),
        ("TODO 风险", str(todos), RED),
        ("关键词命中", str(keywords), VIOLET),
    ]
    x, y = 70, 210
    for idx, (label, value, color) in enumerate(metrics):
        bx = x + idx * 255
        rounded(draw, (bx, y, bx + 225, y + 160))
        draw.text((bx + 24, y + 28), label, fill=MUTED, font=F_BODY)
        draw.text((bx + 24, y + 78), value, fill=color, font=font(46, True))

    draw.text((76, 430), "扫描目录", fill=INK, font=F_H2)
    yy = 488
    for root, count in roots.most_common():
        rounded(draw, (70, yy, W - 70, yy + 78), fill="#ffffff")
        draw.text((100, yy + 22), root, fill=INK, font=F_SMALL)
        draw.text((W - 250, yy + 22), f"{count} 个文件", fill=BLUE, font=F_SMALL)
        yy += 96

    draw.text((76, 760), "参赛亮点：本地运行，不上传文件；既能读代码项目，也能整理 Word/PPT 等个人资料。", fill=MUTED, font=F_BODY)
    return save(img, "01_scan_overview.png")


def bar_chart(data):
    items = data["items"]
    cats = collections.Counter(i["category"] for i in items)
    rows = cats.most_common()
    max_count = max(v for _, v in rows)
    img, draw = canvas("文件类型分布", "快速看出这个目录到底是代码仓库、资料库，还是混合工作区")
    left, top = 260, 230
    bar_w = 870
    for idx, (name, count) in enumerate(rows):
        y = top + idx * 95
        color = PALETTE[idx % len(PALETTE)]
        draw.text((70, y + 14), name, fill=INK, font=F_BODY)
        draw.rounded_rectangle((left, y, left + bar_w, y + 46), radius=12, fill="#e8e1d6")
        width = int(bar_w * count / max_count)
        draw.rounded_rectangle((left, y, left + width, y + 46), radius=12, fill=color)
        draw.text((left + bar_w + 30, y + 8), str(count), fill=color, font=F_BODY)
    return save(img, "02_file_type_distribution.png")


def todo_chart(data):
    hits = data["todo_hits"]
    by_dir = collections.Counter()
    by_kind = collections.Counter(h["kind"] for h in hits)
    for hit in hits:
        path = Path(hit["path"])
        parts = path.parts
        label = "/".join(parts[-3:-1]) if len(parts) >= 3 else path.parent.name
        by_dir[label] += 1
    rows = by_dir.most_common(8)
    max_count = max([v for _, v in rows] or [1])

    img, draw = canvas("代码风险标记分布", "从 TODO/FIXME/HACK 入口快速定位需要继续看的模块")
    draw.text((78, 205), "标记类型", fill=INK, font=F_H2)
    x = 80
    for idx, (kind, count) in enumerate(by_kind.most_common()):
        rounded(draw, (x, 260, x + 250, 375), fill="#ffffff")
        draw.text((x + 24, 282), kind, fill=PALETTE[idx], font=F_BODY)
        draw.text((x + 24, 318), str(count), fill=PALETTE[idx], font=font(34, True))
        x += 280

    draw.text((78, 445), "命中较多的目录", fill=INK, font=F_H2)
    left, top = 410, 510
    for idx, (label, count) in enumerate(rows):
        y = top + idx * 42
        color = PALETTE[idx % len(PALETTE)]
        short = label if len(label) <= 34 else "..." + label[-31:]
        draw.text((80, y - 2), short, fill=INK, font=F_SMALL)
        draw.rounded_rectangle((left, y, left + 760, y + 24), radius=9, fill="#e8e1d6")
        width = int(760 * count / max_count)
        draw.rounded_rectangle((left, y, left + width, y + 24), radius=9, fill=color)
        draw.text((1190, y - 4), str(count), fill=color, font=F_SMALL)
    return save(img, "03_code_todo_risks.png")


def keyword_image(data):
    hits = data["keyword_hits"]
    img, draw = canvas("文档关键词命中", "把散落的学习资料、组会记录和论文材料先找出来")
    if not hits:
        draw.text((90, 270), "本次没有关键词命中，可以换关键词重新扫描。", fill=MUTED, font=F_BODY)
        return save(img, "04_document_keyword_hits.png")

    y = 220
    for idx, hit in enumerate(hits[:6]):
        color = PALETTE[idx % len(PALETTE)]
        rounded(draw, (70, y, W - 70, y + 150), fill="#ffffff")
        kw = " / ".join(hit["keywords"])
        draw.text((100, y + 24), kw, fill=color, font=F_H2)
        path = hit["path"]
        short_path = path if len(path) <= 82 else "..." + path[-79:]
        draw.text((100, y + 66), short_path, fill=INK, font=F_SMALL)
        preview = hit["preview"] or "命中文件名"
        if len(preview) > 88:
            preview = preview[:85] + "..."
        draw.text((100, y + 100), preview, fill=MUTED, font=F_TINY)
        y += 170
    return save(img, "04_document_keyword_hits.png")


def large_files(data):
    rows = sorted(data["items"], key=lambda x: x["size"], reverse=True)[:10]
    max_size = max([r["size"] for r in rows] or [1])
    img, draw = canvas("大文件与素材提醒", "自动发现 PPT、视频和大型源码文件，适合做资料归档入口")
    left, top = 470, 230
    for idx, item in enumerate(rows):
        y = top + idx * 58
        color = PALETTE[idx % len(PALETTE)]
        name = item["name"]
        if len(name) > 28:
            name = name[:25] + "..."
        draw.text((80, y - 2), name, fill=INK, font=F_SMALL)
        draw.rounded_rectangle((left, y, left + 680, y + 30), radius=10, fill="#e8e1d6")
        width = int(680 * item["size"] / max_size)
        draw.rounded_rectangle((left, y, left + width, y + 30), radius=10, fill=color)
        draw.text((1180, y - 2), human_size(item["size"]), fill=color, font=F_SMALL)
    return save(img, "05_large_files.png")


def html_dashboard(data, image_paths):
    extra = [
        BASE / "assets" / "06_code_analysis_overview.png",
        BASE / "assets" / "07_function_purpose_cards.png",
    ]
    all_paths = image_paths + [p for p in extra if p.exists()]
    rels = [p.relative_to(BASE).as_posix() for p in all_paths]
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>自我帮助小助手可视化看板</title>
  <style>
    body {{ margin: 0; font-family: "Microsoft YaHei", Arial, sans-serif; background: #f7f4ee; color: #1f2933; }}
    header {{ padding: 38px 52px 20px; border-bottom: 1px solid #d8d2c6; }}
    h1 {{ margin: 0 0 10px; font-size: 36px; }}
    p {{ margin: 0; color: #61707d; font-size: 18px; }}
    main {{ padding: 32px 52px 60px; display: grid; gap: 28px; }}
    img {{ width: min(100%, 1100px); border: 1px solid #ded7ca; border-radius: 8px; background: white; }}
  </style>
</head>
<body>
  <header>
    <h1>自我帮助小助手可视化看板</h1>
    <p>本地扫描散落资料，并对代码项目做函数级分析，生成可截图、可复用的工作地图。</p>
  </header>
  <main>
    {''.join(f'<img src="{rel}" alt="report chart" />' for rel in rels)}
  </main>
</body>
</html>
"""
    path = BASE / "自我帮助小助手_可视化看板.html"
    path.write_text(html, encoding="utf-8-sig")
    return path


def main():
    data = load_data()
    paths = [
        summary_card(data),
        bar_chart(data),
        todo_chart(data),
        keyword_image(data),
        large_files(data),
    ]
    dashboard = html_dashboard(data, paths)
    print("Generated assets:")
    for path in paths:
        print(path)
    print(dashboard)


if __name__ == "__main__":
    main()
