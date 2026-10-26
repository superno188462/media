"""文字转语音，输出一行 JSON。

用法::

    uv run python scripts/tts.py --text "你好" --out a.mp3
    uv run python scripts/tts.py --voices
    uv run python scripts/tts.py --text "测试" --out a.mp3 --dry-run

实现都在 ``content.tts``，这里只负责命令行与 JSON 输出。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

sys.path.insert(0, str(_HERE.parents[1] / "src"))

from content import ffmpeg as ffmpeg_tool  # noqa: E402
from content import tts as tts_tool  # noqa: E402


def fail(code: str, message: str, hint: str = "") -> int:
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if hint:
        payload["error"]["hint"] = hint
    print(json.dumps(payload, ensure_ascii=False))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", help="要合成的文本")
    parser.add_argument("--file", help="从 UTF-8 文件读取（与 --text 二选一）")
    parser.add_argument("--speaker", default=tts_tool.DEFAULT_SPEAKER,
                        help="音色短名（keai/vv/...）或完整 ID")
    parser.add_argument("--format", default="mp3", choices=["mp3", "wav"])
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--speed", type=float, default=None)
    parser.add_argument("--loudness", type=float, default=None)
    parser.add_argument("--emotion", default=None)
    parser.add_argument("--out", help="输出音频路径")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--voices", action="store_true")
    args = parser.parse_args()

    if args.voices:
        print(json.dumps({
            "ok": True,
            "data": {
                "resource_id": tts_tool.RESOURCE_ID,
                "default": tts_tool.DEFAULT_SPEAKER,
                "voices": tts_tool.VOICES,
                "note": "只有 *_uranus_bigtts 与 saturn_*_tob 两族可用",
            },
        }, ensure_ascii=False, indent=2))
        return 0

    speaker = tts_tool.resolve_speaker(args.speaker)

    if args.file:
        path = Path(args.file)
        if not path.exists():
            return fail("INVALID_ARGS", f"文本文件不存在：{path}")
        text = path.read_text(encoding="utf-8").strip()
    elif args.text:
        text = args.text.strip()
    else:
        return fail("INVALID_ARGS", "需要 --text 或 --file")

    if not text:
        return fail("INVALID_ARGS", "文本为空")
    if not args.out:
        return fail("INVALID_ARGS", "需要 --out 指定输出路径")

    out = Path(args.out)

    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "data": {
                "dry_run": True, "speaker": speaker, "format": args.format,
                "sample_rate": args.sample_rate, "speed": args.speed,
                "chars": len(text), "out": str(out),
                "url": tts_tool.TTS_URL, "resource_id": tts_tool.RESOURCE_ID,
            },
        }, ensure_ascii=False, indent=2))
        return 0

    try:
        tts_tool.synthesize_to_file(
            text, out,
            speaker=speaker, fmt=args.format, sample_rate=args.sample_rate,
            speed=args.speed, loudness=args.loudness, emotion=args.emotion,
        )
    except tts_tool.TtsError as exc:
        return fail("TTS_FAILED", str(exc), "查 --voices 里的可用音色，或检查 VOLC_API_KEY")
    except Exception as exc:  # noqa: BLE001
        return fail("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")

    duration = ffmpeg_tool.probe_duration_ms(out)
    print(json.dumps({
        "ok": True,
        "data": {
            "path": str(out),
            "bytes": out.stat().st_size,
            "speaker": speaker,
            "format": args.format,
            "sample_rate": args.sample_rate,
            "chars": len(text),
            "duration_ms": duration,
            "duration_source": "ffmpeg" if duration is not None else "unavailable",
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
