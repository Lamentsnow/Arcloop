## Arcaea 切片练习制作工具

这是一个用于 **批量生成 Arcaea 高难谱面练习切片** 的小工具。  
通过一份统一的 `slices.json` 配置，脚本会为每首曲目自动：

- 创建切片谱面目录（`<原曲id>_<start>_<end>`）
- 复制曲绘等资源
- 按时间区间切出并平移 `2.aff`
- 使用 `ffmpeg` 切出并循环 `base.ogg`
- 基于 `songlist_example.json` 生成切片条目并写入 `songs/songlist`

这样可以在游戏中以“练习切片包”的形式，集中练习某些困难段落。

---

## 环境与依赖

- **Python**：建议 3.10 及以上
- **ffmpeg**：已安装并在命令行可用（用于 OGG 处理）
  - Windows 可参考常见教程，将 `ffmpeg.exe` 所在目录加入 `PATH`

---

## 目录结构概览

项目根目录下的主要文件/目录：

- `main.py`：一键主流程脚本（目录+曲绘、AFF 切片、OGG 切片、songlist）
- `module1_create_slice_dirs.py`：模块一，创建切片目录并复制资源
- `module2_slice_aff.py`：模块二，AFF 切片与循环
- `module3_slice_ogg.py`：模块三，OGG 切片与循环（依赖 ffmpeg）
- `module4_songlist.py`：模块四，生成并写入切片 `songlist` 条目
- `slices.json`：切片规划配置（各曲目的 start/end/name）
- `songlist_example.json`：原曲 songlist 示例，提供元数据模板
- `songs/`：游戏使用的资源目录
  - `songs/<id>/`：原曲目录，需包含至少 `2.aff`、`base.ogg`、`base.jpg`（和可选 `base_256.jpg`）
  - `songs/songlist`：游戏实际使用的 songlist 文件（无扩展名）
  - `songs/packlist`：曲包配置，已预置对应的 Practice Slices 包

详细的设计说明可参考 `Arcaea切片练习制作计划.md`。

---

## slices.json 格式说明

`slices.json` 顶层是一个对象，键为原曲 id（对应 `songs/<id>/`），值为一个切片数组，例如：

```json
{
  "pragmatism": [
    { "name": "intro", "start": 1379, "end": 12242 },
    { "name": "trill", "start": 30000, "end": 36000 }
  ],
  "fractureray": [
    { "name": "dense", "start": 103200, "end": 122400 }
  ]
}
```

- `start` / `end`：单位为毫秒，必须是 `int` 且 `end > start`
- `name`：可选，主流程中仅用于生成 `title_localized["en"]` 以及辅助辨认
- 每个切片会生成目录 `songs/<id>_<start>_<end>/`

---

## 快速开始：一键生成所有切片

1. 在 `songs/` 中准备好：
   - 各原曲目录 `songs/<id>/`，至少含 `2.aff` 和 `base.ogg`
   - 曲绘 `base.jpg`（和可选 `base_256.jpg`）
2. 编辑好 `slices.json` 与 `songlist_example.json`
3. 在项目根目录运行：

```bash
python main.py
```

常用参数：

- `--root`：项目根目录（默认为脚本所在目录）
- `--slices`：指定 `slices.json` 路径
- `--songs-dir`：指定 `songs` 目录
- `--songlist-example`：指定 `songlist_example.json` 路径
- `--loop N`：每个切片循环 N 次，中间休息 4 拍（同时作用于 AFF 和 OGG，默认 5）
- `--dry-run`：只打印将要处理的曲目与切片，不实际写入/复制
- `--skip-ogg`：跳过 OGG 生成（仅生成目录、AFF、songlist）

示例：

```bash
# 以默认路径，一次性生成所有切片
python main.py

# 只预览会处理哪些切片，不写文件
python main.py --dry-run

# 只生成目录+AFF+songlist，跳过 OGG
python main.py --skip-ogg
```

---

## 各模块脚本用法

如果需要分步骤调试或只跑部分流程，可以单独运行模块脚本。

### 模块一：目录与资源复制（module1_create_slice_dirs.py）

**职责**：根据 `slices.json` 在 `songs/` 下创建切片目录，并复制除 `.ogg`、`.aff` 外的所有文件（如 `base.jpg`、`base_256.jpg`、wav 等）。

命令示例：

```bash
python module1_create_slice_dirs.py
```

常用参数：

- `--root`：项目根路径（默认当前脚本所在目录）
- `--slices`：`slices.json` 路径（默认 `<root>/slices.json`）
- `--songs-dir`：`songs` 目录路径（默认 `<root>/songs`）
- `--dry-run`：只打印将要创建/复制的内容
- `--overwrite`：目标文件已存在时也覆盖复制

---

### 模块二：AFF 切片（module2_slice_aff.py）

**职责**：按 `[start, end]` 对 `2.aff`（或其它指定文件名）进行切片，并可选循环 N 次，中间休息 4 拍。

命令示例：

```bash
python module2_slice_aff.py --loop 5
```

常用参数：

- `--root` / `--slices` / `--songs-dir`：同上
- `--song ID`：仅处理指定歌曲 id（例如 `fractureray`）
- `--dry-run`：只检查文件与区间，不写输出 aff
- `--aff`：要切片的 aff 文件名（不含扩展名），默认 `2`
- `--loop N`：每个切片循环 N 次，每次之间休息 4 个四分音符

---

### 模块三：OGG 切片（module3_slice_ogg.py）

**职责**：使用 ffmpeg 将 `base.ogg` 按 `[start, end]` 截取成 OGG 切片，并可选循环 N 次，中间插入 4 拍静音；统一使用 `-q:a 5 -map_metadata -1` 以保证游戏兼容性。

命令示例：

```bash
python module3_slice_ogg.py --loop 5
```

常用参数：

- `--root` / `--slices` / `--songs-dir`：同上
- `--song ID`：仅处理指定一首歌曲
- `--dry-run`：只检查，不真正调用 ffmpeg
- `--loop N`：循环次数，与 AFF 保持一致

注意：

- 执行前请确认命令行直接输入 `ffmpeg` 能被识别。

---

### 模块四：songlist 生成（module4_songlist.py）

**职责**：根据 `songlist_example.json` 和 `slices.json`，为每个切片生成一条 songlist 条目，并与原曲条目合并后写入 `songs/songlist`。

命令示例：

```bash
python module4_songlist.py
```

常用参数：

- `--root` / `--slices` / `--songs-dir`：同上
- `--songlist-example`：`songlist_example.json` 路径
- `--dry-run`：只打印原曲/切片条目数量，不写入文件

生成条目的规则：

- `id`：`<原曲id>_<start>_<end>`
- `title_localized.en`：优先使用 `slices.json` 中的 `name`，否则用 `id`
- `audioPreview`：固定为 `0`
- `audioPreviewEnd`：`end - start`
- 其它字段（如 `set`、`bpm`、difficulty 配置等）直接沿用原曲条目

---

## 常见问题（FAQ）

- **Q：为什么运行时报“找不到 slices.json / songlist_example.json / songs 目录”？**  
  **A**：请确认这些文件/目录都放在 `--root` 指定的路径下（默认为脚本所在目录），路径区分大小写。

- **Q：OGG 生成失败 / 没有生成 base.ogg？**  
  **A**：大多是因为系统找不到 `ffmpeg`，或源 `base.ogg` 缺失。请确认 `songs/<id>/base.ogg` 存在，并且命令行可以直接执行 `ffmpeg`。

- **Q：songlist 中没看到切片？**  
  **A**：检查是否运行了主流程或模块四脚本，并确认游戏读取的是 `songs/songlist` 而不是 `songlist_example.json`。

---

## 许可与致谢

本项目仅用于个人 Arcaea 练习与学习用途，请勿用于侵犯版权的传播或商业用途。  
谱面与音频资源版权归原作者及 Arcaea 官方所有。

