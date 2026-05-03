"""
模块三：OGG 切片。按 [start, end] 剪切音频，支持与 AFF 一致的「循环 n 次 + 中间休息 4 拍」。
导出均使用 -q:a 5 -map_metadata -1 以免游戏报错。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def _get_bpm_from_aff(aff_path: Path) -> float:
    """从 2.aff 中第一个 timing(0, bpm, beats); 解析 bpm。"""
    if not aff_path.exists():
        return 120.0
    text = aff_path.read_text(encoding="utf-8")
    m = re.search(r"timing\s*\(\s*0\s*,\s*([\d.]+)\s*,", text)
    if m:
        return float(m.group(1))
    return 120.0


def _run_ffmpeg(args: list[str], cwd: Path | None = None) -> bool:
    """执行 ffmpeg，返回是否成功。"""
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


def slice_ogg(
    src_ogg: Path,
    dst_ogg: Path,
    start_ms: int,
    end_ms: int,
    n_loop: int = 5,
    bpm: float = 120.0,
    dry_run: bool = False,
) -> bool:
    """
    剪切并可选循环：从 src_ogg 截取 [start_ms, end_ms]，循环 n_loop 次，
    每次之间插入「4 个四分音符」时长的静音（按 bpm 计算），写入 dst_ogg。
    n_loop=1 时只输出一段，无静音。
    """
    start_s = start_ms / 1000.0
    duration_s = (end_ms - start_ms) / 1000.0
    # 4 个四分音符 = 240000 / bpm 毫秒
    rest_ms = int(round(240000.0 / bpm))
    rest_s = rest_ms / 1000.0

    if dry_run:
        return True

    if n_loop <= 1:
        # 单段：直接截取，带 -q:a 5 -map_metadata -1
        ok = _run_ffmpeg(
            [
                "-i", str(src_ogg),
                "-ss", str(start_s),
                "-t", str(duration_s),
                "-acodec", "libvorbis",
                "-ar", "44100",
                "-ac", "2",
                "-q:a", "5",
                "-map_metadata", "-1",
                str(dst_ogg),
            ]
        )
        return ok

    with tempfile.TemporaryDirectory(prefix="arcaea_ogg_") as tmp:
        tmp_path = Path(tmp)
        slice_path = tmp_path / "slice.ogg"
        silence_path = tmp_path / "silence.ogg"
        list_path = tmp_path / "concat.txt"
        out_path = tmp_path / "out.ogg"

        # 1) 截取单段切片，固定 44100 双声道便于后面 concat
        if not _run_ffmpeg(
            [
                "-i", str(src_ogg),
                "-ss", str(start_s),
                "-t", str(duration_s),
                "-acodec", "libvorbis",
                "-ar", "44100",
                "-ac", "2",
                "-q:a", "5",
                "-map_metadata", "-1",
                str(slice_path),
            ]
        ):
            return False

        # 2) 生成等长静音（与切片同格式）
        if not _run_ffmpeg(
            [
                "-f", "lavfi",
                "-i", f"anullsrc=r=44100:cl=stereo",
                "-t", str(rest_s),
                "-acodec", "libvorbis",
                "-ar", "44100",
                "-ac", "2",
                "-q:a", "5",
                "-map_metadata", "-1",
                str(silence_path),
            ]
        ):
            return False

        # 3) 拼接：slice, silence, slice, silence, ... (n_loop 段 slice)
        # 使用重新编码而非 -c copy，避免 OGG concat 后时长/时间戳错乱（见 fractureray_103200_122400 等）
        lines = []
        for i in range(n_loop):
            lines.append("file 'slice.ogg'")
            if i < n_loop - 1:
                lines.append("file 'silence.ogg'")
        list_path.write_text("\n".join(lines), encoding="utf-8")

        concat_args = [
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-acodec", "libvorbis", "-ar", "44100", "-ac", "2",
            "-q:a", "5", "-map_metadata", "-1",
            str(out_path),
        ]
        if not _run_ffmpeg(concat_args, cwd=tmp_path):
            return False

        # 4) 复制到目标（避免跨盘 replace 失败）
        dst_ogg.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out_path, dst_ogg)
        return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="模块三：按 [start,end] 剪切 OGG，支持循环 n 次 + 中间休息 4 拍。"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--slices", type=Path, default=None)
    parser.add_argument("--songs-dir", type=Path, default=None)
    parser.add_argument("--song", type=str, default=None, metavar="ID", help="仅处理指定歌曲 id（如 fractureray）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--loop",
        type=int,
        default=5,
        metavar="N",
        help="每个切片循环 N 次，中间休息 4 个四分音符；默认 5",
    )
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

    if args.song:
        slices_data = {k: v for k, v in slices_data.items() if k == args.song}
        if not slices_data:
            raise SystemExit(f"未在 slices.json 中找到歌曲: {args.song}")

    total = 0
    errors: list[str] = []

    for song_id, slice_list in slices_data.items():
        if not isinstance(song_id, str) or not isinstance(slice_list, list):
            continue
        src_ogg = songs_dir / song_id / "base.ogg"
        src_aff = songs_dir / song_id / "2.aff"
        if not src_ogg.exists():
            errors.append(f"{song_id}: 缺少 base.ogg")
            continue

        bpm = _get_bpm_from_aff(src_aff)

        for s in slice_list:
            if not isinstance(s, dict):
                continue
            start = s.get("start")
            end = s.get("end")
            if not isinstance(start, int) or not isinstance(end, int) or end <= start:
                continue
            slice_dir = songs_dir / f"{song_id}_{start}_{end}"
            if not slice_dir.exists():
                errors.append(f"{song_id}_{start}_{end}: 切片目录不存在，请先运行模块一")
                continue
            dst_ogg = slice_dir / "base.ogg"

            ok = slice_ogg(
                src_ogg,
                dst_ogg,
                start,
                end,
                n_loop=args.loop,
                bpm=bpm,
                dry_run=args.dry_run,
            )
            if ok:
                total += 1
                print(f"[ogg] {dst_ogg}")
            else:
                errors.append(f"{song_id}_{start}_{end}: ffmpeg 处理失败")

    print(f"\n共处理 {total} 个切片")
    if errors:
        print("未处理/错误:")
        for e in errors:
            print(f"  - {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
