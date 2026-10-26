"""把一场分镜渲染成 HTML。

不用前端框架：一整段 HTML 字符串 + 一段 CSS，交给浏览器排版。
这样在 Windows 和容器里表现一致（只要装了中文字体）。

视觉目标对齐鲸鱼娘 Day 0 的版式：

- 深海渐变背景 + 光束 + 气泡
- 左上角：Day 徽章 + 品牌条
- 右上角：AI 生成声明
- 左侧：白色圆角卡片（带状态）或大字标题
- 右侧：立绘
- 底部：黑色半透明字幕条
"""

from __future__ import annotations

import base64
import html
from pathlib import Path

from .scenes import LAYOUT_CLOSEUP, LAYOUT_HEADLINE, Card, Scene, Storyboard

FONT_STACK = (
    '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", '
    '"Source Han Sans SC", "WenQuanYi Micro Hei", sans-serif'
)

#: 背景与通用样式。用 __FONT__ 作占位并 str.replace 注入，
#: 不要改成 % 格式化——CSS 里大量 100%/50% 会被当成格式符。
BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: 100%; height: 100%; }
body {
  font-family: __FONT__;
  color: #fff;
  overflow: hidden;
  position: relative;
}
.bg {
  position: absolute; inset: 0;
  background: linear-gradient(180deg, #0d2f66 0%, #0a2450 45%, #061632 100%);
}
.beam {
  position: absolute; top: -20%; width: 12%; height: 140%;
  background: linear-gradient(180deg, rgba(150,205,255,.20), rgba(150,205,255,0) 70%);
  transform: rotate(8deg);
  filter: blur(8px);
}
.bubble {
  position: absolute; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, rgba(210,235,255,.55), rgba(210,235,255,.08));
  border: 1px solid rgba(200,230,255,.25);
}
.seabed {
  position: absolute; left: 0; right: 0; bottom: 0; height: 12%;
  background: linear-gradient(180deg, rgba(4,14,32,.0), #04091a 70%);
}

/* 左右留 96px 安全边距：运镜最多平移/裁掉约 74px，
   边距不够会把角标和声明切掉（实测过）。 */
.topbar { position: absolute; top: 44px; left: 96px; right: 96px;
  display: flex; align-items: center; justify-content: space-between; }
.left-top { display: flex; align-items: center; gap: 16px; }
.badge { background: #fff; color: #10254d; font-weight: 800; font-size: 30px;
  padding: 8px 20px; border-radius: 12px; letter-spacing: .5px; }
.brand { font-size: 22px; color: #cfe3ff; display: flex; align-items: center; gap: 8px; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: #ff5d6c;
  box-shadow: 0 0 10px #ff5d6c; display: inline-block; }
.disclaimer { font-size: 20px; color: #9fbde6; }

.stage { position: absolute; inset: 0; }

.card {
  position: absolute; left: 90px; top: 180px; width: 880px;
  background: #fff; color: #16233a; border-radius: 28px;
  padding: 40px 44px; box-shadow: 0 26px 60px rgba(0,10,30,.45);
}
.card-title { font-size: 42px; font-weight: 800; display: flex; align-items: center; gap: 14px; }
.card-lines { margin-top: 26px; display: flex; flex-direction: column; gap: 16px; }
.line { display: flex; align-items: center; gap: 20px;
  padding: 20px 24px; border-radius: 18px; background: #f3f6fb;
  border: 3px solid transparent; }
.line .idx { width: 46px; height: 46px; border-radius: 50%; background: #dbe4f2;
  color: #4a5b78; font-weight: 800; font-size: 26px;
  display: flex; align-items: center; justify-content: center; flex: 0 0 auto; }
.line .txt { font-size: 34px; font-weight: 700; }
.line .sub { font-size: 24px; color: #6b7c99; margin-top: 6px; font-weight: 500; }
.line.active { background: #eaf2ff; border-color: #2e6bd6; }
.line.active .idx { background: #2e6bd6; color: #fff; }
.line.done { opacity: .55; }
.line.done .idx { background: #cbd5e6; color: #fff; }
.line.done .txt { text-decoration: line-through; text-decoration-thickness: 3px; }
.line.pending .txt { color: #a9b6cc; }
.card-footer { margin-top: 22px; font-size: 24px; color: #6b7c99; }

.title-block { position: absolute; left: 100px; top: 260px; }
.title-block .pre { font-size: 40px; color: #cfe3ff; }
.title-block .main { font-size: 108px; font-weight: 900; line-height: 1.1;
  text-shadow: 0 10px 30px rgba(0,20,60,.6); }
.title-block .sub { font-size: 52px; font-weight: 700; color: #8fc4ff; margin-top: 10px; }

.char { position: absolute; right: 110px; bottom: 200px; height: 620px; }
.char img { height: 100%; width: auto; display: block;
  filter: drop-shadow(0 18px 36px rgba(0,12,32,.55)); }

.caption {
  /* 不要用 left:50% + translateX 居中：那样自动宽度只剩容器的一半，
     max-width 形同虚设，长句会被强行折行。 */
  position: absolute; left: 0; right: 0; bottom: 54px;
  margin: 0 auto; width: fit-content;
  max-width: 1440px; text-align: center;
  background: rgba(3,10,24,.82); border: 2px solid rgba(160,200,255,.25);
  border-radius: 18px; padding: 20px 40px;
  font-size: 42px; line-height: 1.45; font-weight: 600;
  /* 均匀断行：否则长句会把最后一个词单独甩到第二行（如「查。」） */
  text-wrap: balance;
}
.caption:empty { display: none; }

.outro { position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 22px; text-align: center;
  /* 右侧让给立绘，否则片尾文字会被挡住 */
  padding-right: 720px; }
.outro .big { font-size: 76px; font-weight: 900; letter-spacing: 2px; }
.outro .small { font-size: 34px; color: #b9d3f5; }

/* ---------- 版式（VP-DATA-02） ---------- */
body.layout-headline .card,
body.layout-headline .char,
/* title_block 的内容被 headline-text 复用，原块必须隐藏，否则文字重叠 */
body.layout-headline .title-block { display: none; }
body.layout-headline .caption { display: none; }

.headline-text {
  position: absolute; left: 0; right: 0; top: 50%; transform: translateY(-50%);
  padding: 0 160px; text-align: center;
  font-size: 96px; font-weight: 900; line-height: 1.28;
  text-shadow: 0 14px 40px rgba(0, 15, 45, .65);
  text-wrap: balance;
}
.headline-text .hl-mark { color: #8fc4ff; }

body.layout-closeup .card { display: none; }
body.layout-closeup .caption { display: none; }
body.layout-closeup .char {
  right: 0; bottom: 0; height: 940px;
}
.closeup-line {
  position: absolute; left: 110px; top: 50%; transform: translateY(-50%);
  width: 780px;
  font-size: 66px; font-weight: 800; line-height: 1.35;
  text-shadow: 0 10px 30px rgba(0, 15, 45, .6);
  text-wrap: balance;
}
.closeup-line .accent-bar {
  width: 96px; height: 10px; border-radius: 6px;
  background: #4d8ef0; margin-bottom: 28px;
}

body.layout-center_card .char,
body.layout-center_card .title-block { display: none; }
body.layout-center_card .card {
  left: 50%; transform: translateX(-50%); top: 200px; width: 1000px;
}

/* 逐条出现时未到时机的行：占位但透明，卡片高度不变 */
.line.hidden { opacity: 0; }
"""


def _data_uri(path: str) -> str:
    """把图片转成 data URI，避免浏览器去读本地文件路径。"""
    file = Path(path)
    suffix = file.suffix.lower().lstrip(".") or "png"
    mime = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
    payload = base64.b64encode(file.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def _bubbles(count: int = 18) -> str:
    """固定位置的气泡，保证每次截图一致（不能用随机）。"""
    spots = [
        (6, 12, 22), (13, 30, 12), (21, 8, 30), (28, 44, 16), (35, 22, 10),
        (41, 62, 26), (48, 15, 14), (55, 38, 20), (62, 70, 12), (68, 28, 24),
        (74, 52, 16), (81, 18, 10), (86, 64, 28), (91, 34, 14), (17, 74, 18),
        (33, 82, 12), (58, 88, 22), (79, 84, 16),
    ][:count]
    return "".join(
        f'<div class="bubble" style="left:{x}%;top:{y}%;width:{size}px;height:{size}px"></div>'
        for x, y, size in spots
    )


def _beams() -> str:
    return "".join(
        f'<div class="beam" style="left:{left}%"></div>'
        for left in (12, 28, 44, 60, 76, 90)
    )


def _card_html(card: Card, hidden_from: int | None = None) -> str:
    """``hidden_from`` 之后的行走隐藏占位，用于逐条出现。"""
    icon = f"<span>{html.escape(card.icon)}</span>" if card.icon else ""
    title = f'<div class="card-title">{icon}{html.escape(card.title)}</div>'

    rows = []
    for position, line in enumerate(card.lines):
        index = html.escape(line.index) if line.index else ""
        sub = f'<div class="sub">{html.escape(line.sub)}</div>' if line.sub else ""
        hidden = hidden_from is not None and position >= hidden_from
        rows.append(
            f'<div class="line {html.escape(line.state)}{" hidden" if hidden else ""}">'
            f'<div class="idx">{index}</div>'
            f'<div><div class="txt">{html.escape(line.text)}</div>{sub}</div>'
            f"</div>"
        )
    footer = f'<div class="card-footer">{html.escape(card.footer)}</div>' if card.footer else ""
    return (
        f'<div class="card">{title}'
        f'<div class="card-lines">{"".join(rows)}</div>{footer}</div>'
    )


def _title_block_html(block: dict) -> str:
    pre = html.escape(str(block.get("title", "")))
    main = html.escape(str(block.get("main", "")))
    sub = html.escape(str(block.get("sub", "")))
    return (
        f'<div class="title-block">'
        f'<div class="pre">{pre}</div>'
        f'<div class="main">{main}</div>'
        f'<div class="sub">{sub}</div>'
        f"</div>"
    )


def render_html(storyboard: Storyboard, scene: Scene) -> str:
    """生成这一场的完整 HTML。"""
    css = BASE_CSS.replace("__FONT__", FONT_STACK)

    badge = ""
    if scene.badge:
        badge = f'<div class="badge">{html.escape(scene.badge)}</div>'

    topbar = (
        f'<div class="topbar">'
        f'<div class="left-top">{badge}'
        f'<div class="brand"><span class="dot"></span>{html.escape(storyboard.brand)}</div></div>'
        f'<div class="disclaimer">{html.escape(storyboard.disclaimer)}</div>'
        f"</div>"
    )

    parts = [
        f'<div class="bg"></div>',
        _beams(),
        _bubbles(),
        '<div class="seabed"></div>',
        topbar,
    ]

    layout = scene.layout

    if scene.card is not None:
        parts.append(_card_html(scene.card, hidden_from=scene.visible_lines))

    if scene.title_block:
        parts.append(_title_block_html(scene.title_block))

    if scene.pose:
        asset = storyboard.assets.get(scene.pose, "")
        if asset and Path(asset).is_file():
            parts.append(
                f'<div class="char"><img src="{_data_uri(asset)}" alt=""></div>'
            )

    # 版式专属内容
    if layout == LAYOUT_HEADLINE:
        main = ""
        if scene.title_block:
            main = "<br>".join(
                html.escape(str(scene.title_block.get(key, "")))
                for key in ("title", "main", "sub")
                if scene.title_block.get(key)
            )
        main = main or html.escape(scene.caption)
        if main:
            parts.append(f'<div class="headline-text">{main}</div>')
    elif layout == LAYOUT_CLOSEUP:
        if scene.caption:
            parts.append(
                '<div class="closeup-line"><div class="accent-bar"></div>'
                f"{html.escape(scene.caption)}</div>"
            )
    elif scene.outro:
        sub = html.escape(scene.outro_sub)
        parts.append(
            f'<div class="outro"><div class="big">{html.escape(scene.outro)}</div>'
            f'<div class="small">{sub}</div></div>'
        )
    elif scene.caption and layout != LAYOUT_HEADLINE:
        parts.append(f'<div class="caption">{html.escape(scene.caption)}</div>')

    body = "".join(parts)
    return (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{css}</style></head>"
        f"<body class='layout-{html.escape(layout)}'>{body}</body></html>"
    )
