"""
模块二：AFF 切片。按 [start, end] 过滤并平移时间。
- hold/arc 终点超出区间时截断到 end
- arctap 只保留 [start,end] 内的
- 切片使用原 aff 中 t=0 的 timing(bpm, beats)
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _find_first_timing_zero(body_lines: list[str]) -> str | None:
    """从 body 行中找到第一个 timing(0,...); 整行，用于切片头。"""
    for line in body_lines:
        s = line.strip()
        m = re.match(r"timing\s*\(\s*0\s*,\s*([^,]+,\s*[^)]+)\s*\)\s*;\s*$", s)
        if m:
            return f"timing(0,{m.group(1).strip()});"
    return None


def _in_range(t: int, start: int, end: int) -> bool:
    return start <= t <= end


def _clamp(t: int, start: int, end: int) -> int:
    return max(start, min(end, t))


def _shift(t: int, start_ms: int) -> int:
    return t - start_ms


def _process_line(line: str, start_ms: int, end_ms: int) -> str | None:
    """
    处理单行事件：若在 [start_ms, end_ms] 内则返回平移后的行，否则返回 None。
    空白行返回空字符串（保留）；未知行返回 None（丢弃）。
    """
    raw = line
    s = line.strip()
    if not s:
        return ""

    # timing: 只保留 t=0 的那条，在外部统一输出一条
    if re.match(r"timing\s*\(", s):
        return None

    # 地面 Note (t,lane);
    m = re.match(r"^\s*\((\d+)\s*,\s*([^)]+)\)\s*;\s*$", s)
    if m:
        t = int(m.group(1))
        lane = m.group(2)
        if not _in_range(t, start_ms, end_ms):
            return None
        return f"({_shift(t, start_ms)},{lane});"

    # hold(t1,t2,lane);
    m = re.match(r"^\s*hold\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*([^)]+)\)\s*;\s*$", s)
    if m:
        t1, t2 = int(m.group(1)), int(m.group(2))
        lane = m.group(3)
        t1c = _clamp(t1, start_ms, end_ms)
        t2c = _clamp(t2, start_ms, end_ms)
        if t1c >= t2c:
            # 零时长 hold 若在区间内则保留
            if t1 == t2 and _in_range(t1, start_ms, end_ms):
                t_shifted = _shift(t1, start_ms)
                return f"hold({t_shifted},{t_shifted},{lane});"
            return None
        return f"hold({_shift(t1c, start_ms)},{_shift(t2c, start_ms)},{lane});"

    # arc(t1,t2,...,); 完全在区间外的删掉；零时长 arc 若在区间内则保留
    m = re.match(r"^\s*arc\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(.+)\)\s*;\s*$", s)
    if m:
        t1, t2 = int(m.group(1)), int(m.group(2))
        mid = m.group(3)
        t1c = _clamp(t1, start_ms, end_ms)
        t2c = _clamp(t2, start_ms, end_ms)
        if t1c >= t2c:
            if t1 == t2 and _in_range(t1, start_ms, end_ms):
                t_shifted = _shift(t1, start_ms)
                return f"arc({t_shifted},{t_shifted},{mid});"
            return None
        return f"arc({_shift(t1c, start_ms)},{_shift(t2c, start_ms)},{mid});"

    m = re.match(r"^\s*arc\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(.+)\)\s*\[\s*(.*?)\s*\]\s*;\s*$", s, re.DOTALL)
    if m:
        t1, t2 = int(m.group(1)), int(m.group(2))
        mid = m.group(3)
        arctap_part = m.group(4)
        t1c = _clamp(t1, start_ms, end_ms)
        t2c = _clamp(t2, start_ms, end_ms)
        if t1c >= t2c:
            if t1 == t2 and _in_range(t1, start_ms, end_ms):
                t_shifted = _shift(t1, start_ms)
                arctap_times = [int(x) for x in re.findall(r"arctap\s*\(\s*(\d+)\s*\)", arctap_part)]
                kept = [str(_shift(t, start_ms)) for t in arctap_times if _in_range(t, start_ms, end_ms)]
                if kept:
                    return f"arc({t_shifted},{t_shifted},{mid})[arctap({'),arctap('.join(kept)})];"
                return f"arc({t_shifted},{t_shifted},{mid});"
            return None
        # 只保留 [start_ms, end_ms] 内的 arctap
        arctap_times = [int(x) for x in re.findall(r"arctap\s*\(\s*(\d+)\s*\)", arctap_part)]
        kept = [str(_shift(t, start_ms)) for t in arctap_times if _in_range(t, start_ms, end_ms)]
        if kept:
            return f"arc({_shift(t1c, start_ms)},{_shift(t2c, start_ms)},{mid})[arctap({'),arctap('.join(kept)})];"
        return f"arc({_shift(t1c, start_ms)},{_shift(t2c, start_ms)},{mid});"

    # camera(t, ...);
    m = re.match(r"^(\s*)camera\s*\(\s*(\d+)\s*,(.*)$", s)
    if m:
        t = int(m.group(2))
        rest = m.group(3)
        if not _in_range(t, start_ms, end_ms):
            return None
        return f"camera({_shift(t, start_ms)},{rest}"

    # scenecontrol(t, ...);
    m = re.match(r"^(\s*)scenecontrol\s*\(\s*(\d+)\s*,(.*)$", s)
    if m:
        t = int(m.group(2))
        rest = m.group(3)
        if not _in_range(t, start_ms, end_ms):
            return None
        return f"scenecontrol({_shift(t, start_ms)},{rest}"

    # 未知行：丢弃（不保留到切片中）
    return None


def slice_aff(content: str, start_ms: int, end_ms: int) -> str:
    """
    将 AFF 内容按 [start_ms, end_ms] 切片并平移时间。
    返回新的 AFF 字符串。
    """
    lines = content.splitlines()
    out: list[str] = []
    i = 0

    # AudioOffset
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("AudioOffset:"):
            out.append("AudioOffset:0")
            i += 1
            break
        i += 1

    # 第一个 "-"
    while i < len(lines):
        if lines[i].strip() == "-":
            out.append("-")
            i += 1
            break
        i += 1

    body_lines = lines[i:]
    timing_zero = _find_first_timing_zero(body_lines)
    if timing_zero is None:
        timing_zero = "timing(0,120.00,4.00);"  # fallback

    out.append(timing_zero)

    for line in body_lines:
        result = _process_line(line, start_ms, end_ms)
        if result is not None:
            out.append(result)

    return "\n".join(out) + "\n"


def _get_bpm_from_timing_line(timing_line: str) -> float:
    """从 timing(0,bpm,beats); 行解析 bpm。"""
    m = re.search(r"timing\s*\(\s*0\s*,\s*([\d.]+)\s*,", timing_line.strip())
    if m:
        return float(m.group(1))
    return 120.0


def _shift_event_times(line: str, offset_ms: int) -> str:
    """将一行事件中的时间整体加上 offset_ms。非事件行原样返回。"""
    s = line.strip()
    if not s:
        return line

    # (t,lane);
    m = re.match(r"^\s*\((\d+)\s*,\s*([^)]+)\)\s*;\s*$", s)
    if m:
        return f"({int(m.group(1)) + offset_ms},{m.group(2)});"

    # hold(t1,t2,lane);
    m = re.match(r"^\s*hold\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*([^)]+)\)\s*;\s*$", s)
    if m:
        return f"hold({int(m.group(1)) + offset_ms},{int(m.group(2)) + offset_ms},{m.group(3)});"

    # arc(t1,t2,...,); 无 arctap
    m = re.match(r"^\s*arc\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(.+)\)\s*;\s*$", s)
    if m:
        return f"arc({int(m.group(1)) + offset_ms},{int(m.group(2)) + offset_ms},{m.group(3)});"

    # arc(t1,t2,...,)[arctap(tn),...];
    m = re.match(r"^\s*arc\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(.+)\)\s*\[\s*(.*?)\s*\]\s*;\s*$", s, re.DOTALL)
    if m:
        arctap_part = m.group(4)
        shifted_taps = [str(int(x) + offset_ms) for x in re.findall(r"arctap\s*\(\s*(\d+)\s*\)", arctap_part)]
        if shifted_taps:
            return f"arc({int(m.group(1)) + offset_ms},{int(m.group(2)) + offset_ms},{m.group(3)})[arctap({'),arctap('.join(shifted_taps)})];"
        return f"arc({int(m.group(1)) + offset_ms},{int(m.group(2)) + offset_ms},{m.group(3)});"

    # camera(t, ...);
    m = re.match(r"^(\s*)camera\s*\(\s*(\d+)\s*,(.*)$", s)
    if m:
        return f"camera({int(m.group(2)) + offset_ms},{m.group(3)}"

    # scenecontrol(t, ...);
    m = re.match(r"^(\s*)scenecontrol\s*\(\s*(\d+)\s*,(.*)$", s)
    if m:
        return f"scenecontrol({int(m.group(2)) + offset_ms},{m.group(3)}"

    return line


def slice_aff_looped(content: str, start_ms: int, end_ms: int, n: int = 5) -> str:
    """
    切片并循环 n 次，每次之间休息「4 个四分音符」时长（按切片 BPM 计算）。
    返回新的 AFF 字符串。
    """
    single = slice_aff(content, start_ms, end_ms)
    lines = single.splitlines()
    if len(lines) < 3:
        return single
    header = lines[:3]  # AudioOffset, -, timing(0,...)
    body = lines[3:]

    timing_line = header[2]
    bpm = _get_bpm_from_timing_line(timing_line)
    slice_duration_ms = end_ms - start_ms
    # 4 个四分音符 = 4 beats，时长 = 4 * (60000 / bpm) = 240000 / bpm 毫秒
    rest_ms = int(round(240000.0 / bpm))
    period_ms = slice_duration_ms + rest_ms

    out = header.copy()
    for k in range(n):
        for line in body:
            if line.strip():
                out.append(_shift_event_times(line, k * period_ms))
            else:
                out.append(line)

    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="模块二：按 [start,end] 过滤并平移 AFF，输出切片 2.aff。"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--slices", type=Path, default=None)
    parser.add_argument("--songs-dir", type=Path, default=None)
    parser.add_argument("--song", type=str, default=None, metavar="ID", help="仅处理指定歌曲 id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--aff", type=str, default="2", help="要切片的 aff 文件名（不含扩展名），默认 2")
    parser.add_argument(
        "--loop",
        type=int,
        default=5,
        metavar="N",
        help="每个切片循环 N 次，每次之间休息 4 个四分音符（按曲目 BPM）；默认 5",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    slices_path = args.slices or (root / "slices.json")
    songs_dir = args.songs_dir or (root / "songs")
    aff_name = f"{args.aff}.aff"

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
        src_aff = songs_dir / song_id / aff_name
        if not src_aff.exists():
            errors.append(f"{song_id}: 缺少 {aff_name}")
            continue
        content = src_aff.read_text(encoding="utf-8")

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
            dst_aff = slice_dir / aff_name
            if args.loop <= 1:
                sliced = slice_aff(content, start, end)
            else:
                sliced = slice_aff_looped(content, start, end, n=args.loop)
            if not args.dry_run:
                dst_aff.write_text(sliced, encoding="utf-8")
            total += 1
            print(f"[aff] {dst_aff}")

    print(f"\n共处理 {total} 个切片")
    if errors:
        print("未处理/错误:")
        for e in errors:
            print(f"  - {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
