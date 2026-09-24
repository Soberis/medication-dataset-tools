r"""第一视角护士配药视频全平台自动下载工具 (YouTube/抖音/小红书/B站)

核心特点：
  1. 锁定【第一视角】与【手部操作特写】（安瓿瓶、西林瓶、注射器抽吸、配药一镜到底）。
  2. 自动下载到指定数据集目录：`D:\下载\第一人称配药实操视频\`。
  3. 规范命名文件夹与文件：`<platform>_<id> - <视频标题>`。
  4. 自动保存原画视频、完整封面图片 (`cover.jpg`)、结构化元数据 (`info.json`)。
  5. 自动通过 FFmpeg 截取【手部动作特征抽样帧】(`frame_sample.jpg`)，便于在文件管理器中直观核验。

常用命令示例：
  # 1. 启动剪贴板全自动监听（强烈推荐）：随看随粘随下，无缝捕获小红书/抖音/YouTube/B站链接
  python download_nurse_pov.py --watch

  # 2. 直接下载单条视频链接（支持含分享文案的整段复制文本）
  python download_nurse_pov.py "https://v.douyin.com/..."
  python download_nurse_pov.py "https://xhslink.cn/..."
  python download_nurse_pov.py "https://www.youtube.com/shorts/..."

  # 3. 批量从文件读取多条链接下载
  python download_nurse_pov.py --file urls.txt
"""

import sys
from pathlib import Path

# Ensure src can be imported
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.social_downloader import main

if __name__ == "__main__":
    main()
