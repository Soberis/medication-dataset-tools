"""Download 8 Xiaohongshu videos with full metadata, covers, frames, and dedup check."""

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
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright

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


async def run_batch():
    profile_dir = Path("./data/browser_profile_xhs").resolve()
    resolved_items = []

    print("==================================================", flush=True)
    print("🚀 启动小红书 8 位护士配药视频解析与全量抓取流程", flush=True)
    print("==================================================", flush=True)

    print("\n[阶段 1/3] 解析 8 条短链接的重定向及安全访问凭证...", flush=True)
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
            print(f"  [{idx}/8] 笔记 ID: {note_id}", flush=True)
        except Exception as e:
            print(f"  [{idx}/8] 短链解析失败: {e}", flush=True)

    print("\n[阶段 2/3] 调取真实 Chrome 会话逐条嗅探高清原画直链与博主档案...", flush=True)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            channel="chrome",
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )

        for item in resolved_items:
            idx = item["index"]
            pc_url = item["pc_url"]
            target_id = item["note_id"]
            print(f"\n--------------------------------------------------", flush=True)
            print(f"[{idx}/8] 正在提取笔记: {target_id} ...", flush=True)
            page = await context.new_page()
            try:
                await page.goto(pc_url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(2500)

                data = await page.evaluate("""(targetId) => {
                    const map = window.__INITIAL_STATE__?.note?.noteDetailMap || {};
                    const keys = Object.keys(map);
                    const entry = map[targetId] || (keys.length ? map[keys[0]] : {}) || {};
                    const item = entry.note || {};
                    const user = item.user || {};
                    const video = item.video || {};
                    const media = video.media || {};
                    const stream = media.stream || {};
                    
                    // Collect all available stream candidates across all stream codecs/keys
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
                                            bitrate: s.videoBitrate || s.avgBitrate || 0,
                                            width: s.width || 0,
                                            height: s.height || 0
                                        };
                                    }
                                }
                            }
                        }
                    }
                    
                    return {
                        title: item.title || '',
                        desc: item.desc || '',
                        type: item.type || '',
                        time: item.time || 0,
                        author: user.nickname || '',
                        userId: user.userId || '',
                        userAvatar: user.avatar || '',
                        videoDuration: video.duration || (video.capa ? video.capa.duration : 0),
                        bestStream: bestStream,
                        coverUrl: (item.imageList && item.imageList[0] && item.imageList[0].urlDefault) || ''
                    };
                }""", target_id)

                if not data:
                    print(f"  ⚠️ 未提取到笔记详情: {pc_url}", flush=True)
                    continue

                item.update(data)
                profile_url = f"https://www.xiaohongshu.com/user/profile/{data['userId']}"
                item["profile_url"] = profile_url

                print(f"  👩‍⚕️ 博主姓名: 【{data['author']}】", flush=True)
                print(f"  🔗 博主主页: {profile_url}", flush=True)
                print(f"  🎬 视频标题: {data['title'] or '(纯标题无文本)'}", flush=True)
                print(f"  ⏱ 视频时长: {data['videoDuration']}s", flush=True)

                best_stream = data.get("bestStream")
                if not best_stream or not best_stream.get("url"):
                    print(f"  ❌ 未找到可用视频流地址", flush=True)
                    continue

                stream_url = best_stream["url"]
                clean_title = sanitize_filename(data["title"] or "小红书配药实操")
                author_clean = sanitize_filename(data["author"] or "xhs_user")
                folder_name = f"xhs_{item['note_id']} - {clean_title} - {author_clean}"
                target_dir = DEFAULT_DOWNLOAD_DIR / folder_name
                target_dir.mkdir(parents=True, exist_ok=True)

                video_file = target_dir / f"{item['note_id']}.mp4"
                info_file = target_dir / f"{item['note_id']}.info.json"
                cover_file = target_dir / "cover.jpg"
                frame_file = target_dir / "frame_sample.jpg"

                meta = {
                    "platform": "xiaohongshu",
                    "id": item["note_id"],
                    "title": data["title"],
                    "uploader": data["author"],
                    "uploader_id": data["userId"],
                    "uploader_url": profile_url,
                    "duration": data["videoDuration"],
                    "description": data["desc"],
                    "url": item["pc_url"],
                    "short_url": item["short_url"],
                    "stream_info": best_stream,
                }
                info_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

                if data.get("coverUrl") and not cover_file.exists():
                    download_stream(data["coverUrl"], cover_file)

                if video_file.exists() and video_file.stat().st_size > 1024 * 500:
                    mb = video_file.stat().st_size / (1024 * 1024)
                    print(f"  📦 视频文件已存在，无需重复拉取 ({mb:.2f} MB)", flush=True)
                else:
                    print(f"  ⬇️ 正在下载高清原画视频流 ({best_stream.get('quality')}, ~{best_stream.get('size', 0)/1024/1024:.1f} MB)...", flush=True)
                    ok = download_stream(stream_url, video_file)
                    if ok:
                        mb = video_file.stat().st_size / (1024 * 1024)
                        print(f"  🎉 视频下载成功！大小: {mb:.2f} MB", flush=True)
                    else:
                        print(f"  ❌ 视频下载失败", flush=True)

                if video_file.exists():
                    extract_representative_frame(video_file, frame_file, data["videoDuration"])

            except Exception as e:
                print(f"  ❌ 发生异常: {e}", flush=True)
            finally:
                await page.close()

        await context.close()

    # Save summary json
    out_file = Path("data/xhs_extracted_creators.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(resolved_items, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n==================================================", flush=True)
    print("✅ 8 位小红书博主配药视频全部抓取完成！", flush=True)
    print("==================================================", flush=True)


if __name__ == "__main__":
    asyncio.run(run_batch())
