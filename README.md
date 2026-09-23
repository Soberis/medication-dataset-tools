# B 站配药视频下载工具 v0.1

搜索配药操作视频候选，人工确认第一视角和手部操作，再批量下载选中的视频。标题和关键词只能帮助缩小范围，不能证明视频符合要求。仅下载和使用有相应权限的视频，尊重原作者和平台规则。

## 安装

需要 Python 3.11+ 和 `ffmpeg`（视频音频合并及 MP4 转封装）。

```powershell
python -m pip install -r requirements.txt
ffmpeg -version
```

## 使用

```powershell
python main.py search
```

搜索读取 `config/keywords.txt`，每个关键词默认取 50 条。yt-dlp 会读取候选元数据以取得标题和 BV 号，但不会下载视频。结果按 BV 号去重并追加到 `data/candidates.csv`；再次搜索会保留已有行的 `selected`。可用 `--limit 30` 调整每个关键词的结果数。

打开 CSV 中的 `url`，快速预览并将合格行的 `selected` 从 `0` 改为 `1`。确认画面接近操作者视角、手持续可见、确实在操作药品，且抽液、开瓶或配液等动作清楚。PPT、讲课、远景及只有几秒配药动作的视频不选。编辑 CSV 时请保留表头和 `bvid`、`url` 列。

```powershell
python main.py download
```

下载只处理 `selected=1` 的行。每个 BV 的文件放在 `data/videos/BV.../`，包含 MP4、`info.json` 和平台提供时的缩略图。`data/downloaded.txt` 是 yt-dlp 的下载档案；再次运行会跳过已完成的视频，失败行可重试，未完成的分片可续传。成功和失败写入 `data/download.log`。如果某个视频不可访问或未提供缩略图，日志会记录实际结果。

`search` 即使某个关键词失败，也会继续其余关键词并保存已找到的候选；退出码非零表示本次有搜索失败。搜索阶段不下载视频。CSV 用 UTF-8 BOM 写入，便于 Excel 打开。
