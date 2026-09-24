"""Unified Downloader for Clinical Nurse POV Medication Videos across Platforms.

Supports:
  - Douyin (抖音)
  - Xiaohongshu (小红书)
  - YouTube (Shorts & Standard Videos)
  - Bilibili (B站)

Automatically downloads into standardized directory:
  ~/Downloads/第一人称配药实操视频/<prefix>_<id> - <title>/
Each directory includes:
  - <id>.mp4 (Clean video stream)
  - <id>.cover.jpg / cover.jpg (Thumbnail)
  - frame_sample.jpg (Extracted representative hand-operation frame via FFmpeg)
  - <id>.info.json (Complete structured metadata)
"""

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yt_dlp

DEFAULT_OUTPUT_DIR = Path("D:/下载/第一人称配药实操视频")
OLD_OUTPUT_DIRS = [Path("D:/下载"), Path.home() / "Downloads" / "第一人称配药实操视频"]
USER_AGENT_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)
USER_AGENT_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("social_downloader")


def sanitize_filename(name: str, max_len: int = 60) -> str:
    """Sanitize title for file/folder name across Windows/Linux."""
    clean = re.sub(r'[\\/*?:"<>|#\r\n\t]+', " ", name).strip()
    clean = re.sub(r"\s+", " ", clean)
    if len(clean) > max_len:
        clean = clean[:max_len].strip()
    return clean or "untitled"


def extract_first_url(text: str) -> Optional[str]:
    """Extract http/https URL from user input text (e.g. mobile share clips)."""
    match = re.search(r"https?://[^\s<>\"']+", text)
    if match:
        url = match.group(0).rstrip("，。！；、\uff09\uff08)")
        return url
    return None


def resolve_redirect_url(url: str, headers: Optional[Dict[str, str]] = None, max_retries: int = 3) -> str:
    """Follow HTTP redirects and return the final destination URL with retry mechanism."""
    hdrs = headers or {"User-Agent": USER_AGENT_MOBILE}
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.geturl()
        except Exception as e:
            if attempt == max_retries - 1:
                logger.warning(f"resolve_redirect_url failed for {url} after {max_retries} attempts: {e}")
                return url
            time.sleep(1.5 * (attempt + 1))
    return url


def download_stream(url: str, dest_path: Path, headers: Optional[Dict[str, str]] = None, max_retries: int = 5) -> bool:
    """Stream download binary file with chunking and retries."""
    import requests
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_path.with_suffix(dest_path.suffix + ".part")
    hdrs = dict(headers or {})
    if "User-Agent" not in hdrs:
        hdrs["User-Agent"] = USER_AGENT_DESKTOP
    if "Referer" not in hdrs:
        if "douyinvod.com" in url or "douyin.com" in url:
            hdrs["Referer"] = "https://www.douyin.com/"
        elif "xhscdn.com" in url or "xiaohongshu.com" in url:
            hdrs["Referer"] = "https://www.xiaohongshu.com/"

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=3)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    for attempt in range(1, max_retries + 1):
        try:
            with session.get(url, headers=hdrs, stream=True, timeout=35) as r:
                r.raise_for_status()
                with open(part_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 512):
                        if chunk:
                            f.write(chunk)
            if part_path.exists() and part_path.stat().st_size > 0:
                part_path.replace(dest_path)
                return dest_path.exists() and dest_path.stat().st_size > 0
        except Exception as e:
            logger.warning(f"Download stream attempt {attempt}/{max_retries} failed for {url[:80]}...: {e}")
            if part_path.exists():
                try:
                    part_path.unlink()
                except Exception:
                    pass
            time.sleep(1.5 * attempt)

    return False


def extract_representative_frame(video_path: Path, output_image_path: Path, duration: float = 0) -> bool:
    """Extract representative frame focusing on hands/actions via FFmpeg."""
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
        logger.warning(f"Frame extraction failed for {video_path.name}: {e}")
        return False


# ==========================================
# Xiaohongshu Downloader
# ==========================================
def download_xiaohongshu(share_text: str, output_root: Path = DEFAULT_OUTPUT_DIR) -> bool:
    raw_url = extract_first_url(share_text)
    if not raw_url:
        logger.error(f"未在输入中找到小红书链接：{share_text}")
        return False

    logger.info(f"[小红书] 解析链接：{raw_url}")
    resolved_url = resolve_redirect_url(raw_url, headers={"User-Agent": USER_AGENT_MOBILE})
    logger.info(f"[小红书] 跳转目标：{resolved_url}")

    match = re.search(r"/(?:discovery/item|explore)/([a-f0-9]{24})", resolved_url)
    if not match:
        logger.error(f"[小红书] 无法从目标 URL 提取笔记 ID: {resolved_url}")
        return False
    note_id = match.group(1)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(resolved_url, download=False)
        except Exception as e:
            logger.error(f"[小红书] yt-dlp 元数据获取失败: {e}")
            return False

    if not info:
        logger.error("[小红书] 未获取到笔记信息")
        return False

    title = info.get("title") or "小红书配药视频"
    clean_title = sanitize_filename(title)
    uploader = info.get("uploader") or info.get("uploader_id") or "xhs_user"
    duration = info.get("duration") or 0
    thumbnail = info.get("thumbnail")

    folder_name = f"xhs_{note_id} - {clean_title}"
    target_dir = output_root / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)
    video_path = target_dir / f"{note_id}.mp4"
    info_path = target_dir / f"{note_id}.info.json"
    cover_path = target_dir / f"{note_id}.cover.jpg"
    cover_generic = target_dir / "cover.jpg"
    frame_path = target_dir / "frame_sample.jpg"

    metadata = {
        "platform": "xiaohongshu",
        "id": note_id,
        "title": title,
        "uploader": uploader,
        "duration": duration,
        "url": resolved_url,
        "original_share": raw_url,
        "tags": info.get("tags", []),
        "description": info.get("description", ""),
    }
    info_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    if thumbnail:
        download_stream(thumbnail, cover_path)
        if cover_path.exists() and not cover_generic.exists():
            shutil.copy2(cover_path, cover_generic)

    if video_path.exists() and video_path.stat().st_size > 1024 * 100:
        logger.info(f"[小红书] 本地已存在完整视频，跳过下载：{video_path}")
        extract_representative_frame(video_path, frame_path, duration)
        return True

    formats = info.get("formats") or []
    formats.sort(key=lambda f: (f.get("width") or 0) * (f.get("height") or 0), reverse=True)
    stream_url = formats[0].get("url") if formats else info.get("url")

    if not stream_url:
        logger.error("[小红书] 未找到可用视频流地址")
        return False

    logger.info(f"[小红书] 开始下载高清视频到: {video_path}")
    success = download_stream(stream_url, video_path)
    if success:
        logger.info(f"[小红书] 下载成功！大小: {video_path.stat().st_size / 1024 / 1024:.2f} MB")
        extract_representative_frame(video_path, frame_path, duration)
    return success


# ==========================================
# Douyin Downloader (via Playwright)
# ==========================================
async def _extract_douyin_via_playwright(aweme_id: str) -> Optional[Dict[str, Any]]:
    from playwright.async_api import async_playwright

    video_url = f"https://www.douyin.com/video/{aweme_id}"
    logger.info(f"[抖音] 正在启动无头浏览器嗅探原画流与签名：{video_url}")

    profile_dir = Path("./data/browser_profile").resolve()
    captured_detail: Optional[Dict[str, Any]] = None

    async with async_playwright() as p:
        if profile_dir.exists():
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=True,
                user_agent=USER_AGENT_DESKTOP,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"],
            )
            browser = None
        else:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=USER_AGENT_DESKTOP,
                viewport={"width": 1280, "height": 800},
            )
        page = context.pages[0] if context.pages else await context.new_page()

        async def handle_response(resp):
            nonlocal captured_detail
            if "aweme/v1/web/aweme/detail" in resp.url and resp.status == 200:
                try:
                    payload = await resp.json()
                    if "aweme_detail" in payload:
                        captured_detail = payload["aweme_detail"]
                except Exception:
                    pass

        context.on("response", handle_response)
        try:
            await page.goto(video_url, wait_until="commit", timeout=25000)
        except Exception as e:
            logger.warning(f"[抖音] 页面导航提示: {e}")

        for _ in range(30):
            if captured_detail:
                break
            await asyncio.sleep(0.5)

        if browser:
            await browser.close()
        else:
            await context.close()

    return captured_detail


def download_douyin(share_text: str, output_root: Path = DEFAULT_OUTPUT_DIR) -> bool:
    raw_url = extract_first_url(share_text)
    if not raw_url:
        logger.error(f"未在输入中找到抖音链接：{share_text}")
        return False

    logger.info(f"[抖音] 解析链接：{raw_url}")
    resolved_url = resolve_redirect_url(raw_url, headers={"User-Agent": USER_AGENT_MOBILE})
    logger.info(f"[抖音] 跳转目标：{resolved_url}")

    match = re.search(r"/(?:video|share/video)/([0-9]{15,22})", resolved_url)
    if not match:
        logger.error(f"[抖音] 无法提取视频 ID: {resolved_url}")
        return False
    aweme_id = match.group(1)

    detail = asyncio.run(_extract_douyin_via_playwright(aweme_id))
    if not detail:
        logger.error("[抖音] 未能捕获视频详情数据")
        return False

    desc = detail.get("desc") or "抖音配药视频"
    clean_title = sanitize_filename(desc)
    author = detail.get("author", {}).get("nickname") or "douyin_user"
    clean_author = sanitize_filename(author, max_len=20)
    duration = (detail.get("duration") or 0) / 1000.0

    folder_name = f"douyin_{aweme_id} - {clean_title} - {clean_author}"
    target_dir = output_root / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)
    video_path = target_dir / f"{aweme_id}.mp4"
    info_path = target_dir / f"{aweme_id}.info.json"
    cover_path = target_dir / f"{aweme_id}.cover.jpg"
    cover_generic = target_dir / "cover.jpg"
    frame_path = target_dir / "frame_sample.jpg"

    sec_uid = detail.get("author", {}).get("sec_uid", "")
    metadata = {
        "platform": "douyin",
        "id": aweme_id,
        "title": desc,
        "uploader": author,
        "sec_uid": sec_uid,
        "duration": duration,
        "url": resolved_url,
        "original_share": raw_url,
    }
    info_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    video_data = detail.get("video", {})
    cover_urls = (
        video_data.get("origin_cover", {}).get("url_list")
        or video_data.get("cover", {}).get("url_list")
        or []
    )
    if cover_urls:
        download_stream(cover_urls[0], cover_path)
        if cover_path.exists() and not cover_generic.exists():
            shutil.copy2(cover_path, cover_generic)

    if video_path.exists() and video_path.stat().st_size > 1024 * 100:
        logger.info(f"[抖音] 本地已存在完整视频，跳过下载：{video_path}")
        extract_representative_frame(video_path, frame_path, duration)
        return True
    for old_dir in OLD_OUTPUT_DIRS:
        if old_dir.exists() and old_dir != output_root:
            for old_f in old_dir.glob(f"*{aweme_id}*"):
                if old_f.is_dir() and list(old_f.glob("*.mp4")):
                    logger.info(f"[抖音] 历史数据集中已存在该视频，跳过下载：{old_f.name}")
                    return True

    bitrates = video_data.get("bit_rate") or []
    stream_url = None
    if bitrates:
        bitrates.sort(key=lambda b: b.get("bit_rate") or 0, reverse=True)
        for b in bitrates:
            url_list = b.get("play_addr", {}).get("url_list") or []
            if url_list:
                stream_url = url_list[0]
                break

    if not stream_url:
        stream_url = (video_data.get("play_addr", {}).get("url_list") or [None])[0]

    if not stream_url:
        logger.error("[抖音] 未找到可用视频播放地址")
        return False

    logger.info(f"[抖音] 开始下载高清视频到: {video_path}")
    success = download_stream(stream_url, video_path)
    if success:
        logger.info(f"[抖音] 下载成功！大小: {video_path.stat().st_size / 1024 / 1024:.2f} MB")
        extract_representative_frame(video_path, frame_path, duration)
    return success


async def _fetch_douyin_author_posts_via_playwright(sec_uid: str) -> List[Dict[str, Any]]:
    from playwright.async_api import async_playwright

    profile_url = f"https://www.douyin.com/user/{sec_uid}"
    logger.info(f"[抖音] 正在通过浏览器扫描创作者主页: {profile_url}")

    profile_dir = Path("./data/browser_profile_douyin").resolve()
    if not profile_dir.exists():
        profile_dir = Path("./data/browser_profile").resolve()

    captured_posts: List[Dict[str, Any]] = []

    async with async_playwright() as p:
        launch_kwargs = {
            "headless": True,
            "user_agent": USER_AGENT_DESKTOP,
            "viewport": {"width": 1280, "height": 800},
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if profile_dir.exists():
            context = await p.chromium.launch_persistent_context(user_data_dir=str(profile_dir), **launch_kwargs)
            browser = None
        else:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=USER_AGENT_DESKTOP, viewport={"width": 1280, "height": 800})

        page = context.pages[0] if context.pages else await context.new_page()

        async def handle_response(resp):
            if "aweme/v1/web/aweme/post" in resp.url and resp.status == 200:
                try:
                    data = await resp.json()
                    for item in data.get("aweme_list", []):
                        captured_posts.append({
                            "aweme_id": item.get("aweme_id"),
                            "desc": item.get("desc") or "",
                            "duration": (item.get("duration") or 0) / 1000.0,
                        })
                except Exception:
                    pass

        context.on("response", handle_response)
        try:
            await page.goto(profile_url, wait_until="commit", timeout=25000)
            for _ in range(16):
                if captured_posts:
                    break
                await asyncio.sleep(0.5)

            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 1000)")
                await asyncio.sleep(1.0)
        except Exception as e:
            logger.warning(f"[抖音] 创作者主页访问提示: {e}")

        if browser:
            await browser.close()
        else:
            await context.close()

    return captured_posts


def explore_and_download_douyin_creator(
    author_input: str,
    output_root: Path = DEFAULT_OUTPUT_DIR,
    max_posts: int = 30,
) -> int:
    """Visit creator profile, filter matching medication videos, check duplicates and download."""
    sec_uid = None
    user_match = re.search(r"/user/([a-zA-Z0-9_\-]+)", author_input)
    if user_match:
        sec_uid = user_match.group(1)
    elif author_input.startswith("MS4wLjAB"):
        sec_uid = author_input.strip()
    else:
        raw_url = extract_first_url(author_input) or author_input.strip()
        resolved_url = resolve_redirect_url(raw_url, headers={"User-Agent": USER_AGENT_MOBILE})
        match = re.search(r"/(?:video|share/video)/([0-9]{15,22})", resolved_url)
        if match:
            aweme_id = match.group(1)
            try:
                detail = asyncio.run(_extract_douyin_via_playwright(aweme_id))
                if detail:
                    sec_uid = detail.get("author", {}).get("sec_uid")
            except Exception as e:
                logger.warning(f"[抖音] 获取作者信息异常: {e}")

    if not sec_uid:
        logger.error(f"[抖音] 无法识别创作者 sec_uid: {author_input}")
        return 0

    try:
        posts = asyncio.run(_fetch_douyin_author_posts_via_playwright(sec_uid))
    except Exception as e:
        logger.error(f"[抖音] 获取作者作品列表异常 ({sec_uid}): {e}")
        return 0
    logger.info(f"[抖音] 从作者主页共探测到 {len(posts)} 部作品")

    keywords = ["配药", "配液", "魔法药水", "药", "抽吸", "扎针", "第一视角", "打针", "屁股针", "皮试", "注射", "一镜到底", "输液", "安瓿", "西林瓶"]
    existing_folders = [f.name for f in output_root.iterdir() if f.is_dir()] if output_root.exists() else []
    for old_dir in OLD_OUTPUT_DIRS:
        if old_dir.exists() and old_dir != output_root:
            existing_folders.extend([f.name for f in old_dir.iterdir() if f.is_dir()])

    downloaded = 0
    for p in posts[:max_posts]:
        desc = p["desc"]
        aid = p["aweme_id"]
        if not any(k in desc for k in keywords):
            continue
        if any(aid in f for f in existing_folders):
            logger.info(f"[抖音] 跳过已在库中视频: [{aid}] {desc[:25]}")
            continue

        logger.info(f"✨ [主页发现新合规实操] 正在下载: [{aid}] {desc[:30]}")
        video_url = f"https://www.douyin.com/video/{aid}"
        ok = download_douyin(video_url, output_root=output_root)
        if ok:
            downloaded += 1

    logger.info(f"[抖音] 主页探索完成！本次新增入库: {downloaded} 部视频")
    return downloaded


# ==========================================
# YouTube Downloader (Shorts & Standard POV)
# ==========================================
def download_youtube(
    share_text: str,
    output_root: Path = DEFAULT_OUTPUT_DIR,
    cookies_file: Optional[Path] = None,
) -> bool:
    raw_url = extract_first_url(share_text) or share_text.strip()
    match = re.search(r"(?:v=|/shorts/|youtu\.be/|/embed/)([a-zA-Z0-9_-]{11})", raw_url)
    if not match:
        logger.error(f"[YouTube] 无法从链接提取视频 ID: {raw_url}")
        return False
    video_id = match.group(1)
    standard_url = f"https://www.youtube.com/watch?v={video_id}"

    cookie_candidates = []
    if cookies_file and cookies_file.is_file():
        cookie_candidates.append(cookies_file)
    default_cookie = Path(__file__).resolve().parent.parent / "data" / "youtube_cookies.txt"
    if default_cookie.is_file():
        cookie_candidates.append(default_cookie)

    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    }
    if cookie_candidates:
        ydl_opts["cookiefile"] = str(cookie_candidates[0])

    info = None
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(standard_url, download=False)
        except Exception as e:
            logger.warning(f"[YouTube] 默认通道受限: {e}，尝试切换移动客户端配置...")
            ydl_opts["extractor_args"] = {"youtube": {"player_client": ["android", "web"]}}
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
                    info = ydl2.extract_info(standard_url, download=False)
            except Exception as e2:
                logger.error(f"[YouTube] 获取视频元数据失败: {e2}")
                logger.info("提示：如果提示需登录/bot验证，请提供 --cookies-file 或将导出的 cookies.txt 放入 data/youtube_cookies.txt")
                return False

    if not info:
        logger.error("[YouTube] 未获取到有效视频信息")
        return False

    title = info.get("title") or "YouTube配药视频"
    clean_title = sanitize_filename(title)
    uploader = info.get("uploader") or info.get("channel") or "youtube_user"
    clean_uploader = sanitize_filename(uploader, max_len=20)
    duration = info.get("duration") or 0
    thumbnail = info.get("thumbnail")

    folder_name = f"youtube_{video_id} - {clean_title} - {clean_uploader}"
    target_dir = output_root / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)
    video_path = target_dir / f"{video_id}.mp4"
    info_path = target_dir / f"{video_id}.info.json"
    cover_path = target_dir / f"{video_id}.cover.jpg"
    cover_generic = target_dir / "cover.jpg"
    frame_path = target_dir / "frame_sample.jpg"

    metadata = {
        "platform": "youtube",
        "id": video_id,
        "title": title,
        "uploader": uploader,
        "duration": duration,
        "url": standard_url,
        "original_share": raw_url,
        "tags": info.get("tags", []),
        "description": info.get("description", ""),
    }
    info_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    if thumbnail:
        download_stream(thumbnail, cover_path)
        if cover_path.exists() and not cover_generic.exists():
            shutil.copy2(cover_path, cover_generic)

    if video_path.exists() and video_path.stat().st_size > 1024 * 100:
        logger.info(f"[YouTube] 本地已存在完整视频，跳过下载：{video_path}")
        extract_representative_frame(video_path, frame_path, duration)
        return True

    dl_opts = dict(ydl_opts)
    dl_opts["outtmpl"] = str(target_dir / f"{video_id}.%(ext)s")
    dl_opts["merge_output_format"] = "mp4"

    logger.info(f"[YouTube] 开始下载高清视频到: {video_path}")
    with yt_dlp.YoutubeDL(dl_opts) as ydl_down:
        try:
            ydl_down.download([standard_url])
        except Exception as e:
            logger.error(f"[YouTube] 下载失败: {e}")
            return False

    extract_representative_frame(video_path, frame_path, duration)
    logger.info(f"[YouTube] 下载完成并已成功截取手部特征抽样帧！")
    return True


# ==========================================
# ==========================================
# Bilibili Downloader (Single URL)
# ==========================================
def fetch_bilibili_view(bvid: str) -> Optional[Dict[str, Any]]:
    """Fetch video metadata directly from Bilibili official API as fallback."""
    headers = {"User-Agent": USER_AGENT_DESKTOP, "Referer": "https://www.bilibili.com"}
    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == 0:
                return data.get("data")
    except Exception as e:
        logger.warning(f"[B站] 官方接口元数据请求异常: {e}")
    return None


def download_bilibili_stream_native(bvid: str, dest_path: Path) -> bool:
    """Download video stream directly via Bilibili playurl API."""
    headers = {"User-Agent": USER_AGENT_DESKTOP, "Referer": "https://www.bilibili.com"}
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists() and dest_path.stat().st_size > 1024 * 100:
        return True
    try:
        view_data = fetch_bilibili_view(bvid)
        if not view_data:
            return False
        aid, cid = view_data["aid"], view_data["cid"]
        play_url = f"https://api.bilibili.com/x/player/playurl?avid={aid}&cid={cid}&qn=64&type=mp4&platform=html5"
        req_play = urllib.request.Request(play_url, headers=headers)
        with urllib.request.urlopen(req_play, timeout=10) as resp:
            play_data = json.loads(resp.read().decode("utf-8"))
        if play_data.get("code") != 0:
            return False
        durls = play_data.get("data", {}).get("durl") or []
        if not durls:
            return False
        return download_stream(durls[0]["url"], dest_path, headers=headers)
    except Exception as e:
        logger.error(f"[B站] 官方流直连下载失败: {e}")
        return False


def download_bilibili(
    share_text: str,
    output_root: Path = DEFAULT_OUTPUT_DIR,
    cookies_file: Optional[Path] = None,
) -> bool:
    raw_url = extract_first_url(share_text) or share_text.strip()
    match = re.search(r"(BV[a-zA-Z0-9]{10})", raw_url)
    if not match:
        logger.error(f"[B站] 未找到有效 BV 号：{raw_url}")
        return False
    bvid = match.group(1)
    standard_url = f"https://www.bilibili.com/video/{bvid}"

    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    }
    if cookies_file and cookies_file.is_file():
        ydl_opts["cookiefile"] = str(cookies_file)

    info = None
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(standard_url, download=False)
        except Exception as e:
            logger.warning(f"[B站] yt-dlp 获取信息受限: {e}")

    title = (info.get("title") if info else "") or ""
    uploader = (info.get("uploader") if info else "") or ""
    duration = (info.get("duration") if info else 0) or 0
    thumbnail = info.get("thumbnail") if info else None

    # 若未能从 yt-dlp 获取标题或 UP 主名称（例如遭遇 412），使用官方 Web API 兜底
    if not title or not uploader:
        api_data = fetch_bilibili_view(bvid)
        if api_data:
            if not title:
                title = api_data.get("title") or bvid
            if not uploader:
                uploader = api_data.get("owner", {}).get("name") or ""
            if not duration:
                duration = api_data.get("duration") or 0
            if not thumbnail:
                thumbnail = api_data.get("pic")

    clean_title = sanitize_filename(title or bvid)
    clean_uploader = sanitize_filename(uploader, max_len=20)
    folder_name = f"{bvid} - {clean_title} - {clean_uploader}" if clean_uploader else f"{bvid} - {clean_title}"
    target_dir = output_root / folder_name

    # 兼容与升级旧版本未添加 UP 主名称的文件夹
    if not target_dir.exists():
        for old_dir in output_root.glob(f"{bvid}*"):
            if old_dir.is_dir() and old_dir != target_dir:
                try:
                    old_dir.rename(target_dir)
                    logger.info(f"[B站] 成功将旧文件夹升级为包含 UP 主格式：{target_dir.name}")
                    break
                except Exception as e:
                    logger.warning(f"[B站] 旧目录重命名失败: {e}")

    target_dir.mkdir(parents=True, exist_ok=True)
    video_path = target_dir / f"{bvid}.mp4"
    info_path = target_dir / f"{bvid}.info.json"
    cover_path = target_dir / f"{bvid}.cover.jpg"
    cover_generic = target_dir / "cover.jpg"
    frame_path = target_dir / "frame_sample.jpg"

    metadata = {
        "platform": "bilibili",
        "id": bvid,
        "title": title,
        "uploader": uploader,
        "duration": duration,
        "url": standard_url,
    }
    info_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    if thumbnail:
        download_stream(thumbnail, cover_path)
        if cover_path.exists() and not cover_generic.exists():
            shutil.copy2(cover_path, cover_generic)

    if video_path.exists() and video_path.stat().st_size > 1024 * 100:
        logger.info(f"[B站] 视频已存在，跳过下载：{video_path}")
        extract_representative_frame(video_path, frame_path, duration)
        return True

    dl_opts = dict(ydl_opts)
    dl_opts["outtmpl"] = str(target_dir / f"{bvid}.%(ext)s")
    dl_opts["merge_output_format"] = "mp4"

    success = False
    with yt_dlp.YoutubeDL(dl_opts) as ydl_down:
        try:
            logger.info(f"[B站] 开始下载视频到: {video_path}")
            ydl_down.download([standard_url])
            success = video_path.exists() and video_path.stat().st_size > 1024 * 100
        except Exception as e:
            logger.warning(f"[B站] yt-dlp 下载受限: {e}，尝试官方直连流下载...")

    if not success:
        success = download_bilibili_stream_native(bvid, video_path)

    if success:
        extract_representative_frame(video_path, frame_path, duration)
        logger.info(f"[B站] 下载完成并已生成手部特征抽样帧！")
        return True
    else:
        logger.error(f"[B站] 下载失败: {bvid}")
        return False


# ==========================================
# Unified Dispatcher
# ==========================================
def download_url(
    text: str,
    output_root: Path = DEFAULT_OUTPUT_DIR,
    cookies_file: Optional[Path] = None,
    explore_author: bool = False,
) -> bool:
    """Detect platform from input text/URL and trigger appropriate downloader."""
    url = extract_first_url(text) or text.strip()
    if not url:
        logger.error(f"输入内容中未检测到有效 URL：{text}")
        return False

    if "douyin.com/user/" in url or (explore_author and ("douyin.com" in url or "iesdouyin.com" in url)):
        cnt = explore_and_download_douyin_creator(text, output_root)
        return cnt > 0
    elif "xiaohongshu.com" in url or "xhslink.cn" in url or "xhslink.com" in url:
        return download_xiaohongshu(text, output_root)
    elif "douyin.com" in url or "iesdouyin.com" in url:
        return download_douyin(text, output_root)
    elif "youtube.com" in url or "youtu.be" in url:
        return download_youtube(text, output_root, cookies_file=cookies_file)
    elif "bilibili.com" in url or "b23.tv" in url or re.search(r"BV[a-zA-Z0-9]{10}", text):
        return download_bilibili(text, output_root, cookies_file=cookies_file)
    else:
        logger.error(f"暂不支持该平台链接：{url}")
        return False


def watch_clipboard(output_root: Path = DEFAULT_OUTPUT_DIR) -> None:
    """Listen to clipboard for Douyin, Xiaohongshu, YouTube, and Bilibili links."""
    import time
    try:
        import tkinter as tk
        tk_root = tk.Tk()
        tk_root.withdraw()
    except Exception as e:
        logger.error(f"无法初始化剪贴板监听: {e}")
        return

    print("\n" + "=" * 55)
    print("📋 剪贴板全平台自动下载监听已启动！")
    print("在手机或电脑浏览 小红书 / 抖音 / YouTube / B站，点击【复制链接】即可全自动入库！")
    print(f"目标目录: {output_root}")
    print("自动执行：标题命名、原画视频下载、封面保存、手部特征帧截取。")
    print("按 Ctrl + C 即可退出监听。")
    print("=" * 55 + "\n")

    processed = set()
    last_text = ""
    target_domains = (
        "douyin.com", "iesdouyin.com",
        "xhslink.cn", "xhslink.com", "xiaohongshu.com",
        "youtube.com", "youtu.be",
        "bilibili.com", "b23.tv",
    )

    while True:
        try:
            time.sleep(1.0)
            try:
                current_text = tk_root.clipboard_get()
            except Exception:
                continue

            if current_text and current_text != last_text:
                last_text = current_text
                url = extract_first_url(current_text)
                if url and any(dom in url for dom in target_domains):
                    if url in processed:
                        continue
                    processed.add(url)
                    print(f"\n⚡ [检测到新配药视频链接] 正在为您全自动下载: {url}")
                    download_url(current_text, output_root)
        except KeyboardInterrupt:
            print("\n👋 已退出剪贴板监听模式。")
            break
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="第一人称配药实操视频全平台（小红书/抖音/YouTube/B站）下载管理工具")
    parser.add_argument("url", nargs="?", help="分享链接或包含链接的完整复制文本")
    parser.add_argument("--file", "-f", type=Path, help="包含多个链接的文本文件，每行一个")
    parser.add_argument("--watch", "-w", action="store_true", help="启动剪贴板监听模式，复制链接即可自动下载")
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"保存目录，默认为 {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument("--cookies-file", type=Path, help="可选：Netscape 格式 Cookies 文件（用于解除 YouTube/B站 下载限制）")
    parser.add_argument(
        "--explore-author",
        "-e",
        action="store_true",
        help="连带挖掘：自动进入创作者主页，批量排重并下载其名下所有符合要求的配药实操视频",
    )

    args = parser.parse_args()

    if args.watch:
        watch_clipboard(args.output_dir)
        return 0

    urls_to_download: List[str] = []
    if args.url:
        urls_to_download.append(args.url)
    elif args.file:
        if not args.file.is_file():
            parser.error(f"指定的文件不存在：{args.file}")
        with open(args.file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls_to_download.append(line)
    else:
        parser.print_help()
        return 1

    success_cnt = 0
    fail_cnt = 0
    for item in urls_to_download:
        ok = download_url(item, args.output_dir, cookies_file=args.cookies_file, explore_author=args.explore_author)
        if ok:
            success_cnt += 1
        else:
            fail_cnt += 1

    print("\n" + "=" * 50)
    print(f"下载统计: 成功 {success_cnt} 个，失败 {fail_cnt} 个")
    print(f"存储路径: {args.output_dir}")
    print("=" * 50)
    return 0 if fail_cnt == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
