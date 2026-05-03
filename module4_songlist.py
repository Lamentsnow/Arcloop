"""
模块四：根据 songlist_example.json 与 slices.json 生成切片条目，写入 songs/songlist。
id=文件夹名(song_id_start_end)，title 取自 slices 的 name，audioPreview=0，audioPreviewEnd=end-start，其余沿用原曲配置。
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="模块四：生成切片 songlist 条目并写入 songs/songlist。"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--slices", type=Path, default=None)
    parser.add_argument("--songs-dir", type=Path, default=None)
    parser.add_argument("--songlist-example", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="只打印将写入的切片条目数，不写文件")
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

    with songlist_example_path.open("r", encoding="utf-8") as f:
        example = json.load(f)
    with slices_path.open("r", encoding="utf-8") as f:
        slices_data = json.load(f)

    songs: list = example.get("songs") or []
    if not isinstance(slices_data, dict):
        raise SystemExit("slices.json 顶层必须是 object")

    # 原曲 id -> 原曲条目（深拷贝用）
    by_id: dict[str, dict] = {s["id"]: s for s in songs if isinstance(s, dict) and s.get("id")}

    slice_entries: list[dict] = []
    seen_ids: set[str] = set()

    for song_id, slice_list in slices_data.items():
        if not isinstance(song_id, str) or not isinstance(slice_list, list):
            continue
        base = by_id.get(song_id)
        if not base:
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
            if slice_id in seen_ids:
                continue
            seen_ids.add(slice_id)

            entry = copy.deepcopy(base)
            entry["id"] = slice_id
            entry["title_localized"] = {"en": str(name) if name is not None else slice_id}
            entry["audioPreview"] = 0
            entry["audioPreviewEnd"] = end - start
            slice_entries.append(entry)

    output_songs = songs + slice_entries

    if args.dry_run:
        print(f"原曲条目数: {len(songs)}")
        print(f"新增切片条目数: {len(slice_entries)}")
        print(f"合计: {len(output_songs)}")
        return 0

    songlist_out.parent.mkdir(parents=True, exist_ok=True)
    with songlist_out.open("w", encoding="utf-8") as f:
        json.dump({"songs": output_songs}, f, ensure_ascii=False, indent=2)

    print(f"[songlist] {songlist_out}")
    print(f"原曲 {len(songs)} 条，切片 {len(slice_entries)} 条，合计 {len(output_songs)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
