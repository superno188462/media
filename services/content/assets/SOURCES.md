# 素材来源台账

对外发布前，每张图都要在这里有记录。没有记录的图片不得发布。

## 状态标记

- `original` —— 本项目自产（代码渲染或模型生成并经人工确认）
- `third-party` —— 第三方素材，必须写明授权与用途

## 记录

| 文件 | 来源 | 授权 | 用途 | 生成时间 |
|---|---|---|---|---|
| `avatar.png` | `volcengine:doubao-seedream-5-0-pro` | original（AI 生成，人工确认） | B 站账号头像 | 2026-10-26 |
| `posts/2026-10-26-demo.jpg` | `volcengine:doubao-seedream-5-0-pro` | original（AI 生成） | 图文动态成稿 | 2026-10-26 |

## 已知限制

### Seedream 会自作主张加文字

即使负面提示词里写了 `text, letters, typography, handwriting, slogan`，
模型仍可能在画面里加英文标语（例如杯子上的 "lazy days"）。

**处置**：出图后必须人工检查画面；发现文字时，
(a) 重出，或 (b) 用 Pillow 裁掉含文字的区域。
不要直接发布带未审文字的图——那些文字不是我们写的文案。

### 图像尺寸

B 站图文动态对图片尺寸有上限。渲染器默认长边不超过 1680px（`render.MAX_EDGE`）。
实际发布前需再实机核一次上限值。
