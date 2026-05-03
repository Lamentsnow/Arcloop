"""
变速模块：为每首曲目（原谱与切片）生成 0.8x、0.9x、0.5x 的 aff 与 ogg。
输出：0.aff/0.ogg (0.8x)，1.aff/1.ogg (0.9x)，3.aff/3.ogg (0.5x)。
并更新 songlist 的 difficulties（4 档：0/1/2/3 对应 0.8/0.9/原速/0.5）。
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
from pathlib import Path

# 倍速配置：(ratingClass, 倍速, 输出 aff/ogg 编号, rating)
SPEED_CONFIG = [
    (0, 0.8, "0", 8),   # 0.aff, 0.ogg
    (1, 0.9, "1", 9),   # 1.aff, 1.ogg
    (3, 0.5, "3", 5),  # 3.aff, 3.ogg
]


def _scale_t(t: int, speed: float) -> int:
    """时间缩放：t' = t / speed（慢速时时间轴拉长）"""
    return int(round(t / speed))


def _scale_bpm(bpm: float, speed: float) -> float:
    """BPM 缩放：bpm' = bpm * speed"""
    return round(bpm * speed, 2)


def _scale_line(line: str, speed: float) -> str:
    """将一行事件中的时间乘以 1/speed（取整）。"""
    s = line.strip()
    if not s:
        return line
    scale = 1.0 / speed

    # timing(t,bpm,beats);
    m = re.match(r"^\s*timing\s*\(\s*(\d+)\s*,\s*([\d.]+)\s*,\s*([^)]+)\)\s*;\s*$", s)
    if m:
        t, bpm, beats = int(m.group(1)), float(m.group(2)), m.group(3)
        return f"timing({_scale_t(t, speed)},{_scale_bpm(bpm, speed)},{beats});"

    # (t,lane);
    m = re.match(r"^\s*\((\d+)\s*,\s*([^)]+)\)\s*;\s*$", s)
    if m:
        return f"({_scale_t(int(m.group(1)), speed)},{m.group(2)});"

    # hold(t1,t2,lane);
    m = re.match(r"^\s*hold\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*([^)]+)\)\s*;\s*$", s)
    if m:
        return f"hold({_scale_t(int(m.group(1)), speed)},{_scale_t(int(m.group(2)), speed)},{m.group(3)});"

    # arc(t1,t2,...,); 无 arctap
    m = re.match(r"^\s*arc\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(.+)\)\s*;\s*$", s)
    if m:
        return f"arc({_scale_t(int(m.group(1)), speed)},{_scale_t(int(m.group(2)), speed)},{m.group(3)});"

    # arc(t1,t2,...,)[arctap(tn),...];
    m = re.match(r"^\s*arc\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(.+)\)\s*\[\s*(.*?)\s*\]\s*;\s*$", s, re.DOTALL)
    if m:
        arctap_part = m.group(4)
        scaled_taps = [_scale_t(int(x), speed) for x in re.findall(r"arctap\s*\(\s*(\d+)\s*\)", arctap_part)]
        if scaled_taps:
            return f"arc({_scale_t(int(m.group(1)), speed)},{_scale_t(int(m.group(2)), speed)},{m.group(3)})[arctap({'),arctap('.join(map(str, scaled_taps))})];"
        return f"arc({_scale_t(int(m.group(1)), speed)},{_scale_t(int(m.group(2)), speed)},{m.group(3)});"

    # camera(t, ...);
    m = re.match(r"^(\s*)camera\s*\(\s*(\d+)\s*,(.*)$", s)
    if m:
        return f"camera({_scale_t(int(m.group(2)), speed)},{m.group(3)}"

    # scenecontrol(t, ...);
    m = re.match(r"^(\s*)scenecontrol\s*\(\s*(\d+)\s*,(.*)$", s)
    if m:
        return f"scenecontrol({_scale_t(int(m.group(2)), speed)},{m.group(3)}"

    return line


def scale_aff(content: str, speed: float) -> str:
    """整份 AFF 时间与 timing 的 BPM 按倍速缩放。"""
    lines = content.splitlines()
    out = []
    for line in lines:
        out.append(_scale_line(line, speed))
    return "\n".join(out) + "\n"


def _run_ffmpeg(args: list[str]) -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args,
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def scale_ogg(src_ogg: Path, dst_ogg: Path, speed: float, dry_run: bool = False) -> bool:
    """生成变速 ogg：atempo=speed，并 -q:a 5 -map_metadata -1。"""
    if dry_run:
        return True
    if not src_ogg.exists():
        return False
    return _run_ffmpeg([
        "-i", str(src_ogg),
        "-filter:a", f"atempo={speed}",
        "-acodec", "libvorbis", "-q:a", "5", "-map_metadata", "-1",
        str(dst_ogg),
    ])


def parse_bpm_base(entry: dict) -> float:
    """从 songlist 条目的 bpm_base 字段取值（数字），保留两位小数。"""
    v = entry.get("bpm_base")
    if v is None:
        return 120.0
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return 120.0


def build_difficulties(bpm_base: float) -> list[dict]:
    """生成 4 档 difficulties：0(0.8x), 1(0.9x), 2(原), 3(0.5x)。"""
    return [
        {
            "ratingClass": 0,
            "chartDesigner": "",
            "jacketDesigner": "",
            "bpm_base": round(bpm_base * 0.8, 2),
            "audioOverride": True,
            "rating": 8,
        },
        {
            "ratingClass": 1,
            "chartDesigner": "",
            "jacketDesigner": "",
            "bpm_base": round(bpm_base * 0.9, 2),
            "audioOverride": True,
            "rating": 9,
        },
        {
            "ratingClass": 2,
            "chartDesigner": "",
            "jacketDesigner": "",
            "rating": 10,
        },
        {
            "ratingClass": 3,
            "chartDesigner": "",
            "jacketDesigner": "",
            "bpm_base": round(bpm_base * 0.5, 2),
            "audioOverride": True,
            "rating": 5,
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="变速模块：生成 0.8x/0.9x/0.5x 的 0.aff/1.aff/3.aff 与 0.ogg/1.ogg/3.ogg，并更新 songlist difficulties。"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--songs-dir", type=Path, default=None)
    parser.add_argument("--songlist", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-ogg", action="store_true", help="不生成变速 ogg")
    args = parser.parse_args()

    root = args.root.resolve()
    songs_dir = args.songs_dir or (root / "songs")
    songlist_path = args.songlist or (songs_dir / "songlist")

    if not songs_dir.exists():
        raise SystemExit(f"找不到 songs 目录：{songs_dir}")

    # 1) 找出所有含 2.aff 与 base.ogg 的曲目目录
    song_ids_from_dirs = set()
    for d in songs_dir.iterdir():
        if not d.is_dir() or d.name in ("random", "tutorial", "pack"):
            continue
        if (d / "2.aff").exists() and (d / "base.ogg").exists():
            song_ids_from_dirs.add(d.name)

    # 2) 为每个目录生成 0/1/3 的 aff 和 ogg
    done = 0
    errors = []
    for song_id in sorted(song_ids_from_dirs):
        src_aff = songs_dir / song_id / "2.aff"
        src_ogg = songs_dir / song_id / "base.ogg"
        content = src_aff.read_text(encoding="utf-8")
        for rating_class, speed, suffix, _ in SPEED_CONFIG:
            out_aff = songs_dir / song_id / f"{suffix}.aff"
            out_ogg = songs_dir / song_id / f"{suffix}.ogg"
            if not args.dry_run:
                out_aff.write_text(scale_aff(content, speed), encoding="utf-8")
            if not args.skip_ogg:
                ok = scale_ogg(src_ogg, out_ogg, speed, dry_run=args.dry_run)
                if not ok and not args.dry_run:
                    errors.append(f"{song_id}/{suffix}.ogg 生成失败")
            done += 1
        print(f"[speed] {song_id}")

    # 3) 更新 songlist 的 difficulties
    if songlist_path.exists():
        with songlist_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        songs = data.get("songs") or []
        for entry in songs:
            if not isinstance(entry, dict) or "id" not in entry:
                continue
            bpm_base = parse_bpm_base(entry)
            entry["difficulties"] = build_difficulties(bpm_base)
        if not args.dry_run:
            with songlist_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[songlist] {songlist_path} 已更新 difficulties（4 档）")
    else:
        errors.append(f"songlist 不存在: {songlist_path}，未更新 difficulties")

    print(f"\n共处理 {done} 个变速组（{len(song_ids_from_dirs)} 首曲目 × 3 档）")
    if errors:
        for e in errors:
            print(f"  - {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
