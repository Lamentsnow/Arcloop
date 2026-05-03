"""
特殊模块：仅处理 fvarcanaeden、fvpentiment、fvtestify 的切片（不含原谱）。
- name 以 s 开头 = 6k 段：删除所有原有 scenecontrol → aff/ogg 平移 1000ms → aff 末尾添加两句 scenecontrol。
- 其余 = 4k 段：删除 aff 中所有 scenecontrol 语句。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import module2_slice_aff as m2

# 仅处理这三首含 6k 段的曲目，且只遍历其切片目录（song_id_start_end），不处理原谱目录
SONGS_WITH_6K = ("fvarcanaeden", "fvpentiment", "fvtestify")

# 6k 时在 aff 末尾追加的两句
SCENECONTROL_6K_LINES = [
    "scenecontrol(0,enwidencamera,0.00,1);",
    "scenecontrol(0,enwidenlanes,0.00,1);",
]


def _run_ffmpeg(args: list[str], cwd: Path | None = None) -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args,
            cwd=cwd,
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def process_aff_4k(content: str) -> str:
    """删除所有 scenecontrol 行，保留其余。"""
    lines = content.splitlines()
    out = []
    for line in lines:
        if re.search(r"^\s*scenecontrol\s*\(", line.strip()):
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if content.endswith("\n") else "")


def process_aff_6k(content: str) -> str:
    """先删除所有原有 scenecontrol，再所有事件时间 +1000ms，末尾追加两句 scenecontrol(0,...)。"""
    lines = content.splitlines()
    if len(lines) < 3:
        return content
    header = lines[:3]
    body = lines[3:]
    # 1) 删除所有 scenecontrol 行
    body_no_sc = [line for line in body if not re.search(r"^\s*scenecontrol\s*\(", line.strip())]
    # 2) 剩余行时间 +1000ms
    shifted = []
    for line in body_no_sc:
        if line.strip():
            shifted.append(m2._shift_event_times(line, 1000))
        else:
            shifted.append(line)
    # 3) 末尾追加两句
    new_body = shifted + SCENECONTROL_6K_LINES
    return "\n".join(header + new_body) + "\n"


def process_ogg_prepend_silence(ogg_path: Path, silence_ms: int = 1000, dry_run: bool = False) -> bool:
    """在 ogg 开头插入 silence_ms 毫秒静音，覆盖原文件。"""
    if dry_run:
        return True
    if not ogg_path.exists():
        return False
    silence_s = silence_ms / 1000.0
    with tempfile.TemporaryDirectory(prefix="arcaea_6k_") as tmp:
        tmp_path = Path(tmp)
        silence_file = tmp_path / "silence.ogg"
        list_file = tmp_path / "list.txt"
        out_file = tmp_path / "out.ogg"
        if not _run_ffmpeg(
            [
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", str(silence_s),
                "-acodec", "libvorbis", "-ar", "44100", "-ac", "2",
                "-q:a", "5", "-map_metadata", "-1",
                str(silence_file),
            ]
        ):
            return False
        # concat: 静音 + 原 ogg，用绝对路径（Windows 用正斜杠）
        list_abs = tmp_path / "list_abs.txt"
        list_abs.write_text(
            "file '" + silence_file.resolve().as_posix() + "'\nfile '" + ogg_path.resolve().as_posix() + "'",
            encoding="utf-8",
        )
        if not _run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", str(list_abs), "-c", "copy", str(out_file)]
        ):
            return False
        shutil.copy2(out_file, ogg_path)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="特殊模块：对 fvarcanaeden/fvpentiment/fvtestify 的切片做 4k/6k 处理。"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--slices", type=Path, default=None)
    parser.add_argument("--songs-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    slices_path = args.slices or (root / "slices.json")
    songs_dir = args.songs_dir or (root / "songs")

    if not slices_path.exists():
        raise SystemExit(f"找不到 slices.json：{slices_path}")
    if not songs_dir.exists():
        raise SystemExit(f"找不到 songs 目录：{songs_dir}")

    with slices_path.open("r", encoding="utf-8") as f:
        slices_data = json.load(f)

    if not isinstance(slices_data, dict):
        raise SystemExit("slices.json 顶层必须是 object")

    done_4k = 0
    done_6k = 0
    errors: list[str] = []

    for song_id in SONGS_WITH_6K:
        slice_list = slices_data.get(song_id)
        if not isinstance(slice_list, list):
            continue
        for s in slice_list:
            if not isinstance(s, dict):
                continue
            start = s.get("start")
            end = s.get("end")
            name = s.get("name")
            if not isinstance(start, int) or not isinstance(end, int) or end <= start:
                continue
            slice_id = f"{song_id}_{start}_{end}"
            slice_dir = songs_dir / slice_id
            aff_path = slice_dir / "2.aff"
            ogg_path = slice_dir / "base.ogg"
            if not slice_dir.exists():
                errors.append(f"{slice_id}: 切片目录不存在")
                continue
            if not aff_path.exists():
                errors.append(f"{slice_id}: 缺少 2.aff")
                continue

            name_str = str(name) if name is not None else ""
            is_6k = name_str.strip().lower().startswith("s")

            if is_6k:
                content = aff_path.read_text(encoding="utf-8")
                new_content = process_aff_6k(content)
                if not args.dry_run:
                    aff_path.write_text(new_content, encoding="utf-8")
                done_6k += 1
                print(f"[6k] {slice_id} (aff+1000ms, 末尾加 scenecontrol)")
                if ogg_path.exists():
                    ok = process_ogg_prepend_silence(ogg_path, silence_ms=1000, dry_run=args.dry_run)
                    if not ok:
                        errors.append(f"{slice_id}: OGG 前插 1s 静音失败")
                else:
                    errors.append(f"{slice_id}: 缺少 base.ogg，未处理音频")
            else:
                content = aff_path.read_text(encoding="utf-8")
                new_content = process_aff_4k(content)
                if not args.dry_run:
                    aff_path.write_text(new_content, encoding="utf-8")
                done_4k += 1
                print(f"[4k] {slice_id} (删除 scenecontrol)")

    print(f"\n4k 切片: {done_4k}，6k 切片: {done_6k}")
    if errors:
        print("错误:")
        for e in errors:
            print(f"  - {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
