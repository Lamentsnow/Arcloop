from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def _load_slices(path: Path) -> dict[str, list[dict]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("slices.json 顶层必须是 object/dict")
    return data


def _ensure_dir(path: Path, dry_run: bool) -> None:
    if dry_run:
        return
    path.mkdir(parents=True, exist_ok=True)


def _copy_file(src: Path, dst: Path, *, overwrite: bool, dry_run: bool) -> bool:
    """
    Returns True if a copy was performed, False if skipped.
    """
    if dst.exists() and not overwrite:
        return False
    if dry_run:
        return True
    shutil.copy2(src, dst)
    return True


# 复制时排除的后缀（不复制到切片目录）
_SKIP_SUFFIXES = {".ogg", ".aff"}


def _should_copy_file(path: Path) -> bool:
    """除 .ogg、.aff 外的文件均复制（含曲绘、wav 等）。"""
    return path.is_file() and path.suffix.lower() not in _SKIP_SUFFIXES


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "模块一：根据 slices.json 创建切片目录，并复制原曲目录内除 .ogg、.aff 外的所有文件。\n"
            "（含曲绘 base.jpg、1080_base.jpg、wav 音效等；切片目录命名：原曲id_start_end）"
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="项目根目录（默认：脚本所在目录）",
    )
    parser.add_argument(
        "--slices",
        type=Path,
        default=None,
        help="slices.json 路径（默认：<root>/slices.json）",
    )
    parser.add_argument(
        "--songs-dir",
        type=Path,
        default=None,
        help="songs 目录路径（默认：<root>/songs）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将执行的操作，不实际创建/复制",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="若目标文件已存在，也覆盖复制",
    )
    args = parser.parse_args()

    root: Path = args.root.resolve()
    slices_path: Path = (args.slices.resolve() if args.slices else (root / "slices.json"))
    songs_dir: Path = (args.songs_dir.resolve() if args.songs_dir else (root / "songs"))

    if not slices_path.exists():
        raise FileNotFoundError(f"找不到 slices.json：{slices_path}")
    if not songs_dir.exists():
        raise FileNotFoundError(f"找不到 songs 目录：{songs_dir}")

    slices = _load_slices(slices_path)

    created_dirs = 0
    copied_files = 0
    skipped_files = 0
    missing_sources: list[str] = []

    for song_id, slice_list in slices.items():
        if not isinstance(song_id, str) or not song_id:
            continue
        if not isinstance(slice_list, list):
            continue

        src_song_dir = songs_dir / song_id

        if not src_song_dir.exists() or not src_song_dir.is_dir():
            missing_sources.append(f"{song_id}: 缺少原曲目录 {src_song_dir}")
            continue

        to_copy = [f for f in src_song_dir.iterdir() if _should_copy_file(f)]
        if not to_copy:
            missing_sources.append(f"{song_id}: 原曲目录内无可复制文件（仅复制非 .ogg/.aff）")
            continue

        for s in slice_list:
            if not isinstance(s, dict):
                continue
            start = s.get("start")
            end = s.get("end")
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            if end <= start:
                continue

            slice_dir = songs_dir / f"{song_id}_{start}_{end}"
            if not slice_dir.exists():
                created_dirs += 1
                print(f"[mkdir] {slice_dir}")
            _ensure_dir(slice_dir, args.dry_run)

            for src_f in to_copy:
                dst_f = slice_dir / src_f.name
                did = _copy_file(src_f, dst_f, overwrite=args.overwrite, dry_run=args.dry_run)
                if did:
                    copied_files += 1
                    print(f"[copy] {src_f} -> {dst_f}")
                else:
                    skipped_files += 1
                    print(f"[skip] {dst_f} (已存在)")

    print("\n==== 结果汇总 ====")
    print(f"root: {root}")
    print(f"slices: {slices_path}")
    print(f"songs: {songs_dir}")
    print(f"创建目录: {created_dirs} (dry-run 不实际创建)")
    print(f"复制文件: {copied_files} (dry-run 不实际复制)")
    print(f"跳过文件: {skipped_files}")
    if missing_sources:
        print("\n---- 缺失项（需手动检查） ----")
        for msg in missing_sources:
            print(f"- {msg}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

