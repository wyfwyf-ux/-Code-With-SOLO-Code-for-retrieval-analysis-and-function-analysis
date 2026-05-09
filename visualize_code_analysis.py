#!/usr/bin/env python
"""Generate visual assets for code_analysis_index.json."""

import collections
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE = Path(__file__).resolve().parent
INDEX = BASE / "code_analysis_index.json"
OUT = BASE / "assets"

W, H = 1400, 900
BG = "#f7f4ee"
INK = "#1f2933"
MUTED = "#61707d"
GRID = "#d8d2c6"
CARD = "#fffdf8"
BLUE = "#2f6f9f"
GREEN = "#4f8a5b"
GOLD = "#b8872f"
RED = "#c84c3d"
VIOLET = "#7a5fa8"
PALETTE = [BLUE, GREEN, GOLD, RED, VIOLET, "#377d83", "#8f6b4a", "#5d6f80"]


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


F_TITLE = font(46, True)
F_H2 = font(29, True)
F_BODY = font(23)
F_SMALL = font(18)
F_TINY = font(15)


def load_data():
    return json.loads(INDEX.read_text(encoding="utf-8-sig"))


def save(img, name):
    OUT.mkdir(exist_ok=True)
    path = OUT / name
    img.save(path)
    return path


def canvas(title, subtitle):
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.text((70, 52), title, fill=INK, font=F_TITLE)
    draw.text((74, 114), subtitle, fill=MUTED, font=F_BODY)
    draw.line((70, 163, W - 70, 163), fill=GRID, width=2)
    return img, draw


def rounded(draw, box, fill=CARD, outline="#e3ddd2", radius=16, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def short(text, limit):
    text = str(text)
    return text if len(text) <= limit else "..." + text[-limit + 3 :]


def overview(data):
    files = data["files"]
    funcs = data["functions"]
    by_ext = collections.Counter(Path(f["path"]).suffix.lower() for f in files)
    long_funcs = len([f for f in funcs if f["lines"] >= 80])
    api_count = len([f for f in funcs if f.get("api_purpose")])

    img, draw = canvas("代码分析：函数级理解", "给定一个文件夹，自动提取函数、位置、参数、调用线索和作用说明")
    metrics = [
        ("代码文件", str(len(files)), BLUE),
        ("函数/方法", str(len(funcs)), GREEN),
        ("长函数", str(long_funcs), RED),
        ("API 增强", str(api_count), VIOLET),
    ]
    for idx, (label, value, color) in enumerate(metrics):
        x = 80 + idx * 315
        rounded(draw, (x, 215, x + 270, 370), fill="#ffffff")
        draw.text((x + 24, 245), label, fill=MUTED, font=F_BODY)
        draw.text((x + 24, 295), value, fill=color, font=font(42, True))

    draw.text((80, 445), "文件类型", fill=INK, font=F_H2)
    left, top = 340, 505
    rows = by_ext.most_common(8)
    max_count = max([v for _, v in rows] or [1])
    for idx, (ext, count) in enumerate(rows):
        y = top + idx * 42
        color = PALETTE[idx % len(PALETTE)]
        draw.text((80, y - 2), ext or "[no ext]", fill=INK, font=F_SMALL)
        draw.rounded_rectangle((left, y, left + 760, y + 26), radius=9, fill="#e8e1d6")
        draw.rounded_rectangle((left, y, left + int(760 * count / max_count), y + 26), radius=9, fill=color)
        draw.text((1130, y - 2), str(count), fill=color, font=F_SMALL)
    return save(img, "06_code_analysis_overview.png")


def function_cards(data):
    funcs = sorted(data["functions"], key=lambda x: x["lines"], reverse=True)[:5]
    img, draw = canvas("函数作用示例", "把“这个函数在哪里、做什么、该怎么看”变成可截图的说明卡片")
    y = 215
    for idx, fn in enumerate(funcs):
        color = PALETTE[idx % len(PALETTE)]
        rounded(draw, (70, y, W - 70, y + 112), fill="#ffffff")
        draw.text((100, y + 18), short(fn["name"], 52), fill=color, font=F_H2)
        draw.text((100, y + 55), f"{short(fn['relative'], 78)}:{fn['line']}  |  {fn['lines']} 行", fill=INK, font=F_SMALL)
        purpose = fn.get("api_purpose") or fn.get("purpose") or ""
        draw.text((100, y + 82), short(purpose, 110), fill=MUTED, font=F_TINY)
        y += 128
    return save(img, "07_function_purpose_cards.png")


def html(data, paths):
    rels = [p.relative_to(BASE).as_posix() for p in paths]
    content = "".join(f'<img src="{rel}" alt="code analysis chart" />' for rel in rels)
    path = BASE / "代码分析_可视化看板.html"
    path.write_text(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>代码分析可视化看板</title>
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
    <h1>代码分析可视化看板</h1>
    <p>自动把项目里的函数、文件类型和复杂函数整理成可读报告。</p>
  </header>
  <main>{content}</main>
</body>
</html>
""",
        encoding="utf-8-sig",
    )
    return path


def main():
    data = load_data()
    paths = [overview(data), function_cards(data)]
    board = html(data, paths)
    print("Generated code analysis assets:")
    for path in paths:
        print(path)
    print(board)


if __name__ == "__main__":
    main()
