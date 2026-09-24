"""Automated Xiaohongshu Creator Homepage POV Medication Video Harvester.

Iterates through nurse creator homepages, scrolls to inspect all video notes,
filters for clinical medication/puncture/POV keywords, and downloads them in bulk.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

DEFAULT_DOWNLOAD_DIR = Path("D:/下载/第一人称配药实操视频")
OLD_OUTPUT_DIR = Path.home() / "Downloads" / "第一人称配药实操视频"
PROFILE_DIR = Path("./data/browser_profile_xhs").resolve()

# Relevant clinical medication keywords
CLINICAL_KEYWORDS = [
    "配药", "配液", "加药", "抽药", "摆药", "溶药", "推药", "注药",
    "第一视角", "沉浸式", "一镜到底", "扎针", "输液", "屁股针", "皮试",
    "留置针", "静脉", "穿刺", "安瓿", "西林瓶", "生理盐水", "注射器",
    "护士日常", "护士工作", "夜班", "治疗台", "下机", "管路"
]

CREATORS_TO_HARVEST = [
    {"name": "旺旺穗冰冰", "user_id": "66c87c6f000000001d033aef"},
    {"name": "我扎针💉不疼", "user_id": "6868b989000000001b019a63"},
    {"name": "鸽子按时下班", "user_id": "67d2bdf9000000000e02d7a8"},
    {"name": "O呦", "user_id": "64704236000000001c02ac0b"},
    {"name": "李开心", "user_id": "64ef54df0000000004026aec"},
    {"name": "每天都很困", "user_id": "5f148ed3000000000100641f"},
    {"name": "木子李", "user_id": "5b963ad3cc59470001d0e2df"},
    {"name": "一只社区喵喵", "user_id": "689c43af0000000019023583"},
    {"name": "叁叁", "user_id": "5d1b76fe0000000010001151"},
    {"name": "女 亭", "user_id": "65fb04ba000000000600f41b"},
    {"name": "贝贝南瓜", "user_id": "60c3543a0000000001000f20"},
    {"name": "王懿懿", "user_id": "64ccd5df000000000b004caa"},
]


def sanitize_filename(name: str, max_len: int = 50) -> str:
    clean = re.sub(r'[\\/*?:"<>|#\r\n\t]+', " ", name).strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean[:max_len].strip() or "untitled"


def is_clinical_medication(title: str, desc: str = "") -> bool:
    content = f"{title} {desc}".lower()
    return any(kw in content for kw in CLINICAL_KEYWORDS)


def download_stream(url: str, dest_path: Path) -> bool:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_path.with_suffix(dest_path.suffix + ".part")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.xiaohongshu.com/",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(part_path, "wb") as f:
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


def extract_representative_frame(video_path: Path, output_image_path: Path, duration: float = 0) -> bool:
    if output_image_path.exists() and output_image_path.stat().st_size > 0:
        return True
    if not video_path.exists() or video_path.stat().st_size == 0:
        return False
    seek_secs = min(max(duration * 0.25, 5.0), 30.0) if duration >= 10 else 1.0
    seek_time = f"{int(seek_secs // 3600):02d}:{int((seek_secs % 3600) // 60):02d}:{int(seek_secs % 60):02d}"
    cmd = [
        "ffmpeg", "-y", "-ss", seek_time,
        "-i", str(video_path),
        "-vframes", "1", "-q:v", "2",
        str(output_image_path),
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        return output_image_path.exists() and output_image_path.stat().st_size > 0
    except Exception:
        return False


async def harvest_creator(page, creator: Dict[str, str], max_videos: int = 15):
    name = creator["name"]
    user_id = creator["user_id"]
    profile_url = f"https://www.xiaohongshu.com/user/profile/{user_id}"

    print(f"\n==================================================", flush=True)
    print(f"👩‍⚕️ 开始扫荡博主主页: 【{name}】", flush=True)
    print(f"🔗 主页地址: {profile_url}", flush=True)
    print(f"==================================================", flush=True)

    try:
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(3000)

        # Scroll down 2-3 times to load more note cards
        for _ in range(3):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)

        cards = await page.query_selector_all("section.note-item, div.note-item")
        print(f"  📋 主页发现笔记卡片数: {len(cards)}", flush=True)

        downloaded_count = 0
        for idx, card in enumerate(cards, 1):
            if downloaded_count >= max_videos:
                print(f"  已达到博主单次抓取上限 ({max_videos} 部)，进入下一位博主", flush=True)
                break

            # Check if this card is video
            is_video = await card.evaluate("""(el) => {
                const playIcon = el.querySelector('.play-icon, svg, [class*="play"], [class*="video"]');
                return !!playIcon;
            }""")

            # Try to get preliminary card title
            card_title = await card.evaluate("""(el) => {
                const t = el.querySelector('.title, .footer, span');
                return (t ? t.innerText : '').trim();
            }""")

            # Filter non-video
            if not is_video:
                continue

            try:
                # Click card to open modal
                await card.click()
                await page.wait_for_timeout(2500)

                # Extract latest note in modal
                note_detail = await page.evaluate("""() => {
                    const map = window.__INITIAL_STATE__?.note?.noteDetailMap || {};
                    const keys = Object.keys(map);
                    if (!keys.length) return null;
                    const latestKey = keys[keys.length - 1];
                    const item = map[latestKey]?.note || {};
                    const user = item.user || {};
                    const video = item.video || {};
                    const media = video.media || {};
                    const stream = media.stream || {};
                    
                    let bestStream = null;
                    for (const k of Object.keys(stream)) {
                        const arr = stream[k];
                        if (Array.isArray(arr)) {
                            for (const s of arr) {
                                const url = s.masterUrl || (s.backupUrls && s.backupUrls[0]);
                                if (url) {
                                    if (!bestStream || (s.size && s.size > (bestStream.size || 0))) {
                                        bestStream = {
                                            codec: k,
                                            url: url,
                                            quality: s.qualityType || 'HD',
                                            size: s.size || 0,
                                            width: s.width || 0,
                                            height: s.height || 0
                                        };
                                    }
                                }
                            }
                        }
                    }
                    
                    return {
                        id: item.id || latestKey,
                        title: item.title || '',
                        desc: item.desc || '',
                        type: item.type || '',
                        videoDuration: video.duration || (video.capa ? video.capa.duration : 0),
                        author: user.nickname || '',
                        userId: user.userId || '',
                        bestStream: bestStream,
                        coverUrl: (item.imageList && item.imageList[0] && item.imageList[0].urlDefault) || ''
                    };
                }""")

                # Close modal immediately
                close_btn = await page.query_selector(".close-circle, .close, [aria-label='Close']")
                if close_btn:
                    await close_btn.click()
                else:
                    await page.keyboard.press("Escape")
                await page.wait_for_timeout(800)

                if not note_detail or not note_detail.get("bestStream"):
                    continue

                note_id = note_detail["id"]
                title = note_detail["title"] or card_title or "配药实操"
                desc = note_detail["desc"]
                duration = note_detail["videoDuration"]

                # Keyword clinical relevance check
                if not is_clinical_medication(title, desc):
                    # Skip unrelated lifestyle notes
                    continue

                clean_title = sanitize_filename(title)
                folder_name = f"xhs_{note_id} - {clean_title} - {name}"
                target_dir = DEFAULT_DOWNLOAD_DIR / folder_name
                target_dir.mkdir(parents=True, exist_ok=True)

                video_file = target_dir / f"{note_id}.mp4"
                info_file = target_dir / f"{note_id}.info.json"
                cover_file = target_dir / "cover.jpg"
                frame_file = target_dir / "frame_sample.jpg"

                if video_file.exists() and video_file.stat().st_size > 1024 * 500:
                    print(f"  [{idx}] 📦 本地已有，跳过: {clean_title} ({duration}s)", flush=True)
                    continue

                if OLD_OUTPUT_DIR.exists():
                    found_in_old = False
                    for old_f in OLD_OUTPUT_DIR.glob(f"*{note_id}*"):
                        if old_f.is_dir() and list(old_f.glob("*.mp4")):
                            print(f"  [{idx}] 📦 历史数据集中已有，跳过: {clean_title} ({duration}s)", flush=True)
                            found_in_old = True
                            break
                    if found_in_old:
                        continue

                print(f"  [{idx}] 🎬 发现符合实操视频: 《{clean_title}》 (时长: {duration}s)", flush=True)
                stream_url = note_detail["bestStream"]["url"]
                mb_est = (note_detail["bestStream"].get("size") or 0) / (1024 * 1024)
                print(f"      ⬇️ 正在下载原画流 (~{mb_est:.1f} MB)...", flush=True)

                ok = download_stream(stream_url, video_file)
                if ok:
                    mb = video_file.stat().st_size / (1024 * 1024)
                    print(f"      🎉 下载成功！大小: {mb:.2f} MB", flush=True)
                    downloaded_count += 1

                    # Write metadata
                    meta = {
                        "platform": "xiaohongshu",
                        "id": note_id,
                        "title": title,
                        "uploader": name,
                        "uploader_id": user_id,
                        "uploader_url": profile_url,
                        "duration": duration,
                        "description": desc,
                        "url": f"https://www.xiaohongshu.com/explore/{note_id}",
                        "stream_info": note_detail["bestStream"],
                    }
                    info_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

                    # Download cover
                    if note_detail.get("coverUrl") and not cover_file.exists():
                        download_stream(note_detail["coverUrl"], cover_file)

                    # Extract frame sample
                    extract_representative_frame(video_file, frame_file, duration)

            except Exception as e:
                # In case modal is stuck, press Escape
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(500)

        print(f"✅ 博主【{name}】扫荡完成，本次新捕获并下载: {downloaded_count} 部！", flush=True)

    except Exception as e:
        print(f"❌ 访问博主主页异常: {e}", flush=True)


async def main():
    print("==================================================", flush=True)
    print("🚀 启动小红书护士博主主页全自动批量扫荡下载流水线", flush=True)
    print("==================================================", flush=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            channel="chrome",
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()

        for c in CREATORS_TO_HARVEST:
            await harvest_creator(page, c, max_videos=15)

        await context.close()

    print("\n🎉 全部博主主页扫荡下载完毕！正在刷新全局索引...", flush=True)
    # Refresh CSV table
    subprocess.run([sys.executable, "tools/generate_creator_table.py"], check=False)


if __name__ == "__main__":
    asyncio.run(main())
