"""
主流程：按 slices.json 一次性完成「目录+曲绘、AFF 切片、OGG 切片、songlist」。
- 仅对原曲目录存在且具备 2.aff / base.ogg / base.jpg / base_256.jpg 的曲目生成切片；
- songlist 为「原曲列表 + 本次实际生成的切片条目」。
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path

# 使用模块二、三的切片与 OGG 逻辑
import module2_slice_aff as m2
import module3_slice_ogg as m3


def main() -> int:
    parser = argparse.ArgumentParser(
        description="主流程：根据 slices.json 生成所有切片（目录+曲绘、AFF、OGG、songlist）。"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--slices", type=Path, default=None)
    parser.add_argument("--songs-dir", type=Path, default=None)
    parser.add_argument("--songlist-example", type=Path, default=None)
    parser.add_argument(
        "--loop",
        type=int,
        default=5,
        metavar="N",
        help="每个切片循环 N 次，中间休息 4 拍；默认 5",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将处理项，不写文件、不复制")
    parser.add_argument("--skip-ogg", action="store_true", help="跳过 OGG 生成（需 ffmpeg）")
    args = parser.parse_args()

    root = args.root.resolve()
    slices_path = args.slices or (root / "slices.json")
    songs_dir = args.songs_dir or (root / "songs")
    songlist_example_path = args.songlist_example or (root / "songlist_example.json")
    songlist_out = songs_dir / "songlist"

    if not slices_path.exists():
        raise SystemExit(f"找不到 slices.json：{slices_path}")
    if not songlist_example_path.exists():
        raise SystemExit(f"找不到 songlist_example.json：{songlist_example_path}")
    if not songs_dir.exists():
        raise SystemExit(f"找不到 songs 目录：{songs_dir}")

    with slices_path.open("r", encoding="utf-8") as f:
        slices_data = json.load(f)
    if not isinstance(slices_data, dict):
        raise SystemExit("slices.json 顶层必须是 object")

    with songlist_example_path.open("r", encoding="utf-8") as f:
        example = json.load(f)
    base_songs: list = example.get("songs") or []
    by_id: dict[str, dict] = {s["id"]: s for s in base_songs if isinstance(s, dict) and s.get("id")}

    seen_slice_id: set[str] = set()
    slice_entries: list[dict] = []
    done = 0
    errors: list[str] = []

    for song_id, slice_list in slices_data.items():
        if not isinstance(song_id, str) or not isinstance(slice_list, list):
            continue
        base = by_id.get(song_id)
        if not base:
            continue
        src_dir = songs_dir / song_id
        src_aff = src_dir / "2.aff"
        src_ogg = src_dir / "base.ogg"
        if not src_aff.exists():
            errors.append(f"{song_id}: 缺少 2.aff")
            continue
        if not src_ogg.exists() and not args.skip_ogg:
            errors.append(f"{song_id}: 缺少 base.ogg")
            continue

        aff_content = src_aff.read_text(encoding="utf-8")
        bpm = m3._get_bpm_from_aff(src_aff)

        for s in slice_list:
            if not isinstance(s, dict):
                continue
            start = s.get("start")
            end = s.get("end")
            name = s.get("name")
            if not isinstance(start, int) or not isinstance(end, int) or end <= start:
                continue
            slice_id = f"{song_id}_{start}_{end}"
            if slice_id in seen_slice_id:
                continue
            seen_slice_id.add(slice_id)

            slice_dir = songs_dir / slice_id

            # 1) 目录 + 复制除 .ogg、.aff 外的所有文件（曲绘、wav 等）
            if not args.dry_run:
                slice_dir.mkdir(parents=True, exist_ok=True)
                for src_f in src_dir.iterdir():
                    if src_f.is_file() and src_f.suffix.lower() not in (".ogg", ".aff"):
                        shutil.copy2(src_f, slice_dir / src_f.name)

            # 2) AFF
            if args.loop <= 1:
                sliced_aff = m2.slice_aff(aff_content, start, end)
            else:
                sliced_aff = m2.slice_aff_looped(aff_content, start, end, n=args.loop)
            if not args.dry_run:
                (slice_dir / "2.aff").write_text(sliced_aff, encoding="utf-8")

            # 3) OGG
            if not args.skip_ogg and src_ogg.exists():
                ok = m3.slice_ogg(
                    src_ogg,
                    slice_dir / "base.ogg",
                    start,
                    end,
                    n_loop=args.loop,
                    bpm=bpm,
                    dry_run=args.dry_run,
                )
                if not ok and not args.dry_run:
                    errors.append(f"{slice_id}: OGG 生成失败")

            # 4) songlist 条目
            entry = copy.deepcopy(base)
            entry["id"] = slice_id
            entry["title_localized"] = {"en": str(name) if name is not None else slice_id}
            entry["audioPreview"] = 0
            entry["audioPreviewEnd"] = end - start
            slice_entries.append(entry)

            done += 1
            print(f"[{done}] {slice_id}")

    # 5) 写入 songlist
    output_songs = base_songs + slice_entries
    if not args.dry_run:
        songlist_out.parent.mkdir(parents=True, exist_ok=True)
        with songlist_out.open("w", encoding="utf-8") as f:
            json.dump({"songs": output_songs}, f, ensure_ascii=False, indent=2)
        print(f"\n[songlist] {songlist_out}")

    print(f"\n共处理 {done} 个切片，songlist 合计 {len(output_songs)} 条")
    if errors:
        print("错误/跳过:")
        for e in errors:
            print(f"  - {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
