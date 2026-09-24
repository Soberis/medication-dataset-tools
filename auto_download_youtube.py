"""Automated search and batch downloader for Nurse POV Medication Videos on YouTube.

Fully automated:
1. Searches YouTube using targeted nursing POV keywords.
2. Filters for 9:16 Shorts / POV videos focusing on hands (安瓿瓶/西林瓶/抽吸/一镜到底).
3. Automatically discards noise (ASMR, roleplay, lectures, games, sleep-aids).
4. Downloads video, cover, extracts representative hand frame, and saves metadata into:
   ~/Downloads/第一人称配药实操视频/youtube_<id> - <title> - <uploader>/
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import yt_dlp

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads" / "第一人称配药实操视频"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("auto_youtube")

# Targeted search keywords
DEFAULT_KEYWORDS = [
    "沉浸式體驗 護士配藥",
    "沉浸式 护士配药",
    "护士配药 第一视角",
    "護士配藥 第一視角",
    "配药 一镜到底",
    "配藥 一鏡到底",
    "弹安瓿瓶 配药",
    "彈安瓿瓶 配藥",
    "freddie queensbridge 護士",
    "freddie queensbridge 配藥",
]

# Strict blacklist to eliminate roleplay, ASMR, lectures, and gaming
BLACKLIST_TERMS = [
    "asmr", "roleplay", "助眠", "催眠", "耳语", "哄睡", "采耳", "掏耳",
    "洗浴", "按摩", "眼部", "修面", "游戏", "恐怖", "病娇", "动画", "动漫",
    "过山车", "旅游", "直播", "小狗", "讲座", "课件", "ppt", "题库",
    "考试", "英语", "english", "listening", "服药", "吃药",
    "科目", "驾校", "驾照", "考驾", "考駕", "驾驶", "駕駛", "学车", "學車",
    "练车", "練車", "手动挡", "手動擋", "自动挡", "自動擋", "倒车", "倒車",
    "美甲", "做饭", "烹饪", "美食", "开箱", "盲盒",
]

# Whitelist to ensure hand/action relevance
WHITELIST_TERMS = [
    "配药", "配藥", "第一视角", "第一視角", "沉浸式", "一镜到底", "一鏡到底",
    "安瓿", "安瓿瓶", "西林瓶", "抽药", "抽吸", "扎针", "扎針", "皮试", "皮試", "屁股针",
    "加药", "加藥", "排气", "输液", "輸液", "护士", "護士", "药师", "藥師",
    "飞针", "飛針", "小针", "小針", "化药", "化藥", "推注", "抽水", "打针", "打針",
    "静脉输液", "靜脈輸液", "注射", "留置针", "留置針", "抽血", "血培养", "血培養",
    "连配", "連配", "连扎", "連扎", "穿刺",
]


def sanitize_filename(name: str, max_len: int = 60) -> str:
    clean = re.sub(r'[\\/*?:"<>|#\r\n\t]+', " ", name).strip()
    clean = re.sub(r"\s+", " ", clean)
    if len(clean) > max_len:
        clean = clean[:max_len].strip()
    return clean or "untitled"


def extract_representative_frame(video_path: Path, output_image_path: Path, duration: float = 0) -> bool:
    if output_image_path.exists() and output_image_path.stat().st_size > 0:
        return True
    if not video_path.exists() or video_path.stat().st_size == 0:
        return False

    seek_secs = min(max(duration * 0.2, 5.0), 30.0) if duration >= 10 else 1.0
    seek_time = f"{int(seek_secs // 3600):02d}:{int((seek_secs % 3600) // 60):02d}:{int(seek_secs % 60):02d}"

    cmd = [
        "ffmpeg", "-y", "-ss", seek_time,
        "-i", video_path.name,
        "-vframes", "1", "-q:v", "2",
        output_image_path.name,
    ]
    try:
        subprocess.run(
            cmd,
            cwd=str(video_path.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        return output_image_path.exists() and output_image_path.stat().st_size > 0
    except Exception as e:
        logger.warning(f"抽帧失败 ({video_path.name}): {e}")
        return False


def get_already_downloaded_ids(output_dir: Path) -> Set[str]:
    """Scan existing folders to avoid redownloading."""
    downloaded = set()
    if not output_dir.exists():
        return downloaded
    for folder in output_dir.iterdir():
        if folder.is_dir():
            m = re.search(r"(?:youtube_)?([a-zA-Z0-9_-]{11})", folder.name)
            if m:
                downloaded.add(m.group(1))
            # Also check for bvid or douyin
            m2 = re.search(r"([0-9]{15,22})", folder.name)
            if m2:
                downloaded.add(m2.group(1))
            m3 = re.search(r"(BV[a-zA-Z0-9]{10})", folder.name)
            if m3:
                downloaded.add(m3.group(1))
    return downloaded


def is_qualified_candidate(title: str, duration: Optional[float] = None) -> bool:
    """Filter candidate title and duration for nurse POV hand dispensing."""
    title_lower = title.lower()

    # 1. Blacklist check
    for term in BLACKLIST_TERMS:
        if term in title_lower:
            return False

    # 2. Duration check: preference for Shorts / short POV clips (<= 600 seconds)
    if duration is not None and duration > 600:
        return False

    # 3. Whitelist check
    matched_terms = [t for t in WHITELIST_TERMS if t in title_lower]
    if len(matched_terms) >= 1:
        # Extra check: Must contain either 配药/配藥 or 安瓿/抽吸 or 第一视角/一镜到底 or 针/输液
        core_hits = any(t in title_lower for t in [
            "配药", "配藥", "安瓿", "抽吸", "一镜到底", "一鏡到底", "第一视角", "第一視角",
            "扎针", "扎針", "飞针", "飛針", "加药", "加藥", "输液", "輸液", "抽药", "抽藥", "打针", "打針",
            "注射", "留置针", "留置針", "抽血", "皮试", "皮試", "连配", "連配"
        ])
        return core_hits

    return False


def search_youtube_candidates(keyword: str, max_results: int = 15) -> List[Dict[str, Any]]:
    """Search YouTube and return filtered candidate metadata."""
    logger.info(f"[SEARCH] 正在 YouTube 检索关键词：【{keyword}】...")
    cookie_file = ROOT / "data" / "youtube_cookies.txt"
    proxy_url = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "http://127.0.0.1:7890"
    node_path = shutil.which("node") or r"C:\nvm4w\nodejs\node.exe"
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "extract_flat": True,
        "no_warnings": True,
        "proxy": proxy_url,
    }
    if node_path and Path(node_path).exists():
        ydl_opts["js_runtimes"] = {"node": {"path": str(node_path)}}
    if cookie_file.is_file():
        ydl_opts["cookiefile"] = str(cookie_file)

    candidates = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            res = ydl.extract_info(f"ytsearch{max_results * 2}:{keyword}", download=False)
            entries = res.get("entries", [])
            for e in entries:
                if not e:
                    continue
                vid = e.get("id")
                title = e.get("title") or ""
                duration = e.get("duration")
                uploader = e.get("uploader") or ""
                channel_url = e.get("channel_url") or e.get("uploader_url") or ""

                if not vid or not title:
                    continue

                if is_qualified_candidate(title, duration):
                    candidates.append({
                        "id": vid,
                        "title": title,
                        "uploader": uploader,
                        "duration": duration or 0,
                        "url": f"https://www.youtube.com/watch?v={vid}",
                        "channel_url": channel_url,
                    })
                    if len(candidates) >= max_results:
                        break
        except Exception as ex:
            logger.error(f"检索出错 ({keyword}): {ex}")

    logger.info(f"  -> 检索完成，通过【第一视角/看手】初筛匹配到 {len(candidates)} 条高质量候选")
    return candidates


def download_single_youtube(candidate: Dict[str, Any], output_dir: Path) -> bool:
    """Download single candidate video, cover, frame, and metadata."""
    vid = candidate["id"]
    title = candidate["title"]
    clean_title = sanitize_filename(title)
    uploader = sanitize_filename(candidate.get("uploader", ""), max_len=20)

    folder_name = f"youtube_{vid} - {clean_title}" if not uploader else f"youtube_{vid} - {clean_title} - {uploader}"
    target_dir = output_root = output_dir / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)

    video_path = target_dir / f"{vid}.mp4"
    info_path = target_dir / f"{vid}.info.json"
    cover_path = target_dir / f"{vid}.cover.jpg"
    cover_generic = target_dir / "cover.jpg"
    frame_path = target_dir / "frame_sample.jpg"

    if video_path.exists() and video_path.stat().st_size > 1024 * 100:
        logger.info(f"[SKIP] 视频已存在，跳过：{video_path.name}")
        extract_representative_frame(video_path, frame_path, candidate.get("duration", 0))
        return True

    proxy_url = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "http://127.0.0.1:7890"
    node_path = shutil.which("node") or r"C:\nvm4w\nodejs\node.exe"
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo+bestaudio/best",
        "outtmpl": str(target_dir / f"{vid}.%(ext)s"),
        "merge_output_format": "mp4",
        "writethumbnail": True,
        "proxy": proxy_url,
        "retries": 15,
        "fragment_retries": 15,
        "socket_timeout": 30,
        "continuedl": True,
    }
    if node_path and Path(node_path).exists():
        ydl_opts["js_runtimes"] = {"node": {"path": str(node_path)}}
    cookie_file = ROOT / "data" / "youtube_cookies.txt"
    if cookie_file.is_file():
        ydl_opts["cookiefile"] = str(cookie_file)

    logger.info(f"[DOWNLOAD] 开始下载：{title[:40]}...")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([candidate["url"]])
        except Exception as e:
            logger.error(f"下载失败 ({vid}): {e}")
            return False

    # Check for downloaded thumbnail and normalize names
    for f in target_dir.iterdir():
        if f.suffix.lower() in [".jpg", ".webp", ".png"] and f.name != "frame_sample.jpg":
            if not cover_path.exists():
                shutil.copy2(f, cover_path)
            if not cover_generic.exists():
                shutil.copy2(f, cover_generic)

    # Save metadata
    info_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")

    # Extract hand action frame
    extract_representative_frame(video_path, frame_path, candidate.get("duration", 0))
    logger.info(f"[OK] 成功入库并生成手部抽样帧：{target_dir.name}")
    return True


def fetch_channel_candidates(
    channel_url: str,
    uploader_name: str = "",
    max_items: int = 30,
    already_seen_ids: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Scan author's channel (Shorts and Videos) and filter candidate videos."""
    if not channel_url:
        return []

    cookie_file = ROOT / "data" / "youtube_cookies.txt"
    proxy_url = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "http://127.0.0.1:7890"
    node_path = shutil.which("node") or r"C:\nvm4w\nodejs\node.exe"

    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "extract_flat": True,
        "no_warnings": True,
        "proxy": proxy_url,
        "playlist_items": f"1:{max_items}",
    }
    if node_path and Path(node_path).exists():
        ydl_opts["js_runtimes"] = {"node": {"path": str(node_path)}}
    if cookie_file.is_file():
        ydl_opts["cookiefile"] = str(cookie_file)

    candidates = []
    seen = already_seen_ids or set()

    base_url = channel_url.rstrip("/")
    if base_url.endswith("/shorts") or base_url.endswith("/videos"):
        tabs = [base_url]
    else:
        # Check shorts first (priority for 9:16 hands POV), then videos
        tabs = [f"{base_url}/shorts", f"{base_url}/videos"]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for tab_url in tabs:
            tab_name = "Shorts (竖屏)" if "shorts" in tab_url else "视频列表"
            logger.info(f"[CHANNEL] 正在深入访问创作者【{uploader_name or '该作者'}】的 {tab_name} 主页...")
            try:
                res = ydl.extract_info(tab_url, download=False)
                entries = res.get("entries", [])
                for e in entries:
                    if not e:
                        continue
                    vid = e.get("id")
                    title = e.get("title") or ""
                    duration = e.get("duration")
                    uploader = e.get("uploader") or uploader_name

                    if not vid or not title or vid in seen:
                        continue

                    if is_qualified_candidate(title, duration):
                        logger.info(f"  -> [主页匹配成功] 命中合适操作视频: {title[:40]}")
                        seen.add(vid)
                        candidates.append({
                            "id": vid,
                            "title": title,
                            "uploader": uploader,
                            "duration": duration or 0,
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "channel_url": channel_url,
                        })
            except Exception as ex:
                logger.warning(f"创作者主页 ({tab_url}) 读取提示: {ex}")

    return candidates


def auto_download_all(
    keywords: Optional[List[str]] = None,
    channels: Optional[List[str]] = None,
    limit_per_kw: int = 5,
    explore_channel: bool = True,
    channel_limit: int = 30,
    total_max: int = 20,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> int:
    """Run full automated search, filter, author channel crawl, and batch download pipeline."""
    if channels and not keywords:
        kws = []
    else:
        kws = keywords or DEFAULT_KEYWORDS
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_ids = get_already_downloaded_ids(output_dir)

    print("\n" + "=" * 65)
    print(">> YouTube 护士配药第一视角视频全自动批量采集下载启动！")
    print(f">> 目标目录: {output_dir}")
    print(f">> 当前已入库视频: {len(existing_ids)} 部")
    print(">> 核心策略：精准锁定【第一视角】与【手部操作特写】，严格过滤 ASMR/讲解/游戏")
    if explore_channel:
        print(">> 连带挖掘：已开启！发现合规视频后自动进入作者主页批量挖掘同类操作视频")
    print("=" * 65 + "\n")

    all_candidates: List[Dict[str, Any]] = []
    seen_ids = set(existing_ids)
    visited_channels: Set[str] = set()

    # 1. Directly explore specified channels if provided
    if channels:
        for ch in channels:
            if len(all_candidates) >= total_max:
                break
            logger.info(f"[TARGET CHANNEL] 正在扫描指定创作者主页: {ch}")
            ch_cands = fetch_channel_candidates(ch, max_items=channel_limit, already_seen_ids=seen_ids)
            for c in ch_cands:
                all_candidates.append(c)
                if len(all_candidates) >= total_max:
                    break

    # 2. Keyword search + Author homepage expansion
    for kw in kws:
        if len(all_candidates) >= total_max:
            break
        cands = search_youtube_candidates(kw, max_results=limit_per_kw)
        for c in cands:
            vid = c["id"]
            if vid not in seen_ids:
                seen_ids.add(vid)
                all_candidates.append(c)
                if len(all_candidates) >= total_max:
                    break

            # If suitable video found, explore the author's channel
            ch_url = c.get("channel_url")
            uploader = c.get("uploader") or ""
            if explore_channel and ch_url and ch_url not in visited_channels:
                visited_channels.add(ch_url)
                logger.info(f"✨ 发现配药创作者【{uploader}】，深入探索其主页挖掘全部合适视频...")
                ch_cands = fetch_channel_candidates(
                    channel_url=ch_url,
                    uploader_name=uploader,
                    max_items=channel_limit,
                    already_seen_ids=seen_ids,
                )
                for cc in ch_cands:
                    all_candidates.append(cc)
                    if len(all_candidates) >= total_max:
                        break

    print(f"\n[INFO] 共聚合发现 {len(all_candidates)} 部待下载的高质量合规配药视频！开始自动下载...\n")

    success_cnt = 0
    fail_cnt = 0
    for idx, c in enumerate(all_candidates):
        print(f"[{idx + 1}/{len(all_candidates)}] 处理中: {c['title']}")
        ok = download_single_youtube(c, output_dir)
        if ok:
            success_cnt += 1
        else:
            fail_cnt += 1

    print("\n" + "=" * 65)
    print(f">> 自动采集完成！成功下载入库: {success_cnt} 部，失败: {fail_cnt} 部")
    print(f">> 文件位置: {output_dir}")
    print("=" * 65 + "\n")
    return success_cnt


def main():
    parser = argparse.ArgumentParser(description="YouTube 护士配药第一视角视频全自动批量搜索与下载工具")
    parser.add_argument("--keywords", "-k", nargs="*", help="自定义搜索关键词列表")
    parser.add_argument("--channel", "-c", nargs="*", help="指定要全量抓取的创作者主页链接")
    parser.add_argument("--limit", "-l", type=int, default=5, help="每个关键词搜索候选数，默认 5")
    parser.add_argument("--no-explore-channel", action="store_true", help="关闭自动挖掘作者主页功能")
    parser.add_argument("--channel-limit", type=int, default=30, help="挖掘作者主页时最多检查的视频数，默认 30")
    parser.add_argument("--max", "-m", type=int, default=20, help="总下载视频上限，默认 20")
    parser.add_argument("--output-dir", "-o", type=Path, default=DEFAULT_OUTPUT_DIR, help="保存目录")

    args = parser.parse_args()
    auto_download_all(
        keywords=args.keywords,
        channels=args.channel,
        limit_per_kw=args.limit,
        explore_channel=not args.no_explore_channel,
        channel_limit=args.channel_limit,
        total_max=args.max,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
