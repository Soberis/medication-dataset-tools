"""Resolve Xiaohongshu note links, extract authors, homepages, and video streams."""

import asyncio
import json
import logging
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright

# Force unbuffered UTF-8 stdout
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

USER_AGENT_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)

RAW_LINKS = [
    "https://xhslink.cn/o/3tQhLXLhPwI",
    "https://xhslink.cn/o/6rQ5Msm7Kxb",
    "https://xhslink.cn/o/9XUB6sEIky0",
    "https://xhslink.cn/o/5vrcarn8get",
    "https://xhslink.cn/o/7FO2baILGIH",
    "https://xhslink.cn/o/65aHiWKwsB1",
    "https://xhslink.cn/o/5qF7FRg8DF0",
    "https://xhslink.cn/o/K5AFw1KQBp",
]

DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "第一人称配药实操视频"


def resolve_short_url(short_url: str) -> str:
    req = urllib.request.Request(short_url, headers={"User-Agent": USER_AGENT_MOBILE})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.geturl()


def sanitize_filename(name: str, max_len: int = 60) -> str:
    clean = re.sub(r'[\\/*?:"<>|#\r\n\t]+', " ", name).strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean[:max_len].strip() or "untitled"


def download_stream(url: str, dest_path: Path) -> bool:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_path.with_suffix(dest_path.suffix + ".part")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.xiaohongshu.com/",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp, open(part_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 512)
                if not chunk:
                    break
                f.write(chunk)
        if part_path.exists():
            part_path.replace(dest_path)
        return dest_path.exists() and dest_path.stat().st_size > 0
    except Exception as e:
        print(f"    [下载失败] {e}")
        if part_path.exists():
            part_path.unlink()
        return False


async def extract_and_download_all():
    profile_dir = Path("./data/browser_profile_xhs").resolve()
    resolved_items = []

    print("Step 1: 正在解析 8 条短链接的重定向及 xsec_token...", flush=True)
    for idx, u in enumerate(RAW_LINKS, 1):
        try:
            target = resolve_short_url(u)
            m_id = re.search(r"/(?:discovery/item|explore)/([a-f0-9]{24})", target)
            note_id = m_id.group(1) if m_id else ""
            parsed = urllib.parse.urlparse(target)
            q = urllib.parse.parse_qs(parsed.query)
            token = q.get("xsec_token", [""])[0]

            pc_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={urllib.parse.quote(token)}&xsec_source=pc_share"
            resolved_items.append({
                "index": idx,
                "short_url": u,
                "note_id": note_id,
                "xsec_token": token,
                "pc_url": pc_url,
            })
            print(f"  [{idx}/8] Note: {note_id}", flush=True)
        except Exception as e:
            print(f"  [{idx}/8] 解析失败: {e}", flush=True)

    print("\nStep 2: 使用持久化会话逐一解析博主与视频流...", flush=True)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            channel="chrome",
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else await context.new_page()

        for item in resolved_items:
            idx = item["index"]
            pc_url = item["pc_url"]
            print(f"\n[{idx}/8] 正在请求: {item['note_id']} ...", flush=True)
            try:
                await page.goto(pc_url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2500)

                # Extract state
                data = await page.evaluate("""() => {
                    const noteData = window.__INITIAL_STATE__?.note?.noteDetailMap || {};
                    const keys = Object.keys(noteData);
                    if (!keys.length) return null;
                    const item = noteData[keys[0]]?.note || {};
                    const user = item.user || {};
                    const video = item.video || {};
                    const media = video.media || {};
                    const stream = media.stream || {};
                    const h264 = stream.h264 || [];
                    const h265 = stream.h265 || [];
                    const streamUrl = (h264[0] && h264[0].masterUrl) || (h265[0] && h265[0].masterUrl) || '';
                    
                    return {
                        title: item.title || '',
                        desc: item.desc || '',
                        type: item.type || '',
                        time: item.time || 0,
                        author: user.nickname || '',
                        userId: user.userId || '',
                        userAvatar: user.avatar || '',
                        videoDuration: video.duration || (video.capa ? video.capa.duration : 0),
                        streamUrl: streamUrl,
                        coverUrl: (item.imageList && item.imageList[0] && item.imageList[0].urlDefault) || ''
                    };
                }""")

                if data:
                    item.update(data)
                    item["profile_url"] = f"https://www.xiaohongshu.com/user/profile/{data['userId']}"
                    print(f"  ✅ 博主: 【{data['author']}】 (主页: {item['profile_url']})", flush=True)
                    print(f"  📝 标题: {data['title']}", flush=True)
                    print(f"  ⏱ 时长: {data['videoDuration']}s | 类型: {data['type']}", flush=True)

                    # Download video if streamUrl available
                    stream_url = data.get("streamUrl")
                    if stream_url:
                        clean_title = sanitize_filename(data["title"] or "小红书配药视频")
                        author_clean = sanitize_filename(data["author"] or "xhs_user")
                        folder_name = f"xhs_{item['note_id']} - {clean_title} - {author_clean}"
                        target_dir = DEFAULT_DOWNLOAD_DIR / folder_name
                        target_dir.mkdir(parents=True, exist_ok=True)

                        video_file = target_dir / f"{item['note_id']}.mp4"
                        info_file = target_dir / f"{item['note_id']}.info.json"
                        cover_file = target_dir / "cover.jpg"

                        # info.json
                        meta = {
                            "platform": "xiaohongshu",
                            "id": item["note_id"],
                            "title": data["title"],
                            "uploader": data["author"],
                            "uploader_id": data["userId"],
                            "uploader_url": item["profile_url"],
                            "duration": data["videoDuration"],
                            "description": data["desc"],
                            "url": item["pc_url"],
                            "short_url": item["short_url"],
                        }
                        info_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

                        # Cover
                        if data.get("coverUrl") and not cover_file.exists():
                            download_stream(data["coverUrl"], cover_file)

                        # Video
                        if video_file.exists() and video_file.stat().st_size > 1024 * 100:
                            print(f"  📦 视频已存在，跳过下载: {video_file.name}", flush=True)
                        else:
                            print(f"  ⬇️ 正在下载高清原画视频流...", flush=True)
                            ok = download_stream(stream_url, video_file)
                            if ok:
                                mb = video_file.stat().st_size / (1024 * 1024)
                                print(f"  🎉 视频下载成功！({mb:.2f} MB)", flush=True)
                else:
                    print(f"  ⚠️ 未提取到笔记详情: {pc_url}", flush=True)
            except Exception as e:
                print(f"  ❌ 提取出错: {e}", flush=True)

        await context.close()

    out_file = Path("data/xhs_extracted_creators.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(resolved_items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n全部处理完毕！元数据已保存至 {out_file}", flush=True)


if __name__ == "__main__":
    asyncio.run(extract_and_download_all())
