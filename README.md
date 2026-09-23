# B 站配药视频下载工具 v0.1

搜索配药操作视频候选，人工确认第一视角和手部操作，再批量下载选中的视频。标题和关键词只能帮助缩小范围，不能证明视频符合要求。仅下载和使用有相应权限的视频，尊重原作者和平台规则。

## 安装

直接使用本机的 `python`，无需为本项目创建虚拟环境。需要 Python 3.11+、`ffmpeg`（视频音频合并及 MP4 转封装）和 `requirements.txt` 固定的 yt-dlp 版本。本机已安装这些依赖；换机器时再安装：

```powershell
python -m pip install -r requirements.txt
ffmpeg -version
```

## 使用

```powershell
python main.py search
```

搜索读取 `config/keywords.txt`，每个关键词默认取 50 条。yt-dlp 会读取候选元数据以取得标题和 BV 号，但不会下载视频。结果按 BV 号去重并追加到 `data/candidates.csv`；再次搜索会保留已有行的 `selected`。可用 `--limit 30` 调整每个关键词的结果数。新候选中，标题含“第一视角、POV、沉浸式、手部”等线索的行排在前面；CSV 也保存可用的封面链接。`title_hint` 只是预览顺序，不代表已看到手。

打开 CSV 中的 `url`，快速预览并将合格行的 `selected` 从 `0` 改为 `1`。先看封面，再在视频开头、中段和末段各抽看几秒：确认画面接近操作者视角、手部在主要配药段持续可见、手确实操作药品，且抽液、开瓶或配液等动作清楚。即使视频有 10 分钟，只要没有清楚的手部配药动作就不选。PPT、讲课、远景及只有几秒配药动作的视频也不选。编辑 CSV 时请保留表头和 `bvid`、`url` 列。

```powershell
python main.py download
```

下载只处理 `selected=1` 的行。默认保存到系统“下载”目录下的专门文件夹（如 Windows 的 `Downloads/B站视频/BV.../`，可通过 `--output-dir` 自定义），每个 BV 独立文件夹，包含 MP4、`info.json` 和封面缩略图。目标目录下的 `downloaded.txt` 是下载档案，再次运行会跳过已完成的视频，失败行可重试，未完成的分片可续传。成功和失败写入目标目录下的 `download.log`。如果某个视频不可访问或未提供缩略图，日志会记录实际结果。

`search` 会在元数据请求之间短暂停顿，遇到 HTTP 412 时最多重试两次；若连续两个关键词都被 412 拒绝，就停止本轮搜索，避免无效请求。每个关键词完成后立即保存已找到的候选；稍后重跑时已有人工选择不会丢失。退出码非零表示本次有搜索失败。搜索阶段不下载视频。CSV 用 UTF-8 BOM 写入，便于 Excel 打开。

如果 B 站对匿名请求持续返回 HTTP 412，可自行选择使用当前登录的浏览器：`python main.py search --cookies-from-browser edge`，下载时也加 `--cookies-from-browser edge`。默认不读取浏览器 Cookie；请只在自己信任的电脑上使用此选项。

若 Windows 拒绝浏览器 Cookie 解密，可使用自己导出的 Netscape 格式 Cookie 文件：`python main.py search --cookies-file C:\path\to\cookies.txt`，下载时同样传入 `--cookies-file`。Cookie 文件包含登录凭据，放在仓库外，不要提交或分享其内容；工具只需要文件路径。

运行 `python -m unittest discover tests` 时出现的 BV 号和“失败”文字来自模拟数据，用来验证单条失败后继续；测试不访问 B 站或下载视频。
