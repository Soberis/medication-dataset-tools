"""Download single Xiaohongshu video from link or share text."""

import asyncio
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

USER_AGENT_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)

DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "第一人称配药实操视频"
PROFILE_DIR = Path("./data/browser_profile_xhs").resolve()


def extract_url(text: str) -> str:
    m = re.search(r"https?://[^\s<>\"']+", text)
    if not m:
        raise ValueError(f"未找到链接: {text}")
    return m.group(0).rstrip("，。！；、\uff09\uff08)")


def resolve_short_url(short_url: str) -> str:
    req = urllib.request.Request(short_url, headers={"User-Agent": USER_AGENT_MOBILE})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.geturl()


def sanitize_filename(name: str, max_len: int = 50) -> str:
    clean = re.sub(r'[\\/*?:"<>|#\r\n\t]+', " ", name).strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean[:max_len].strip() or "untitled"


async def download_note(raw_input: str):
    raw_url = extract_url(raw_input)
    print(f"🔗 正在解析输入链接: {raw_url}", flush=True)

    target_url = resolve_short_url(raw_url)
    print(f"🎯 重定向目标: {target_url}", flush=True)

    m_id = re.search(r"/(?:discovery/item|explore)/([a-f0-9]{24})", target_url)
    if not m_id:
        print("❌ 无法从目标链接提取笔记 ID")
        return False
    note_id = m_id.group(1)

    q = urllib.parse.parse_qs(urllib.parse.urlparse(target_url).query)
    token = q.get("xsec_token", [""])[0]
    pc_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={urllib.parse.quote(token)}&xsec_source=pc_share"
    print(f"📦 笔记 ID: {note_id}, 访问地址: {pc_url}", flush=True)

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            channel="chrome",
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        try:
            print("🌐 正在通过真实 Chrome 会话获取元数据与流媒体直链...", flush=True)
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
            }""", note_id)

            if not data or not data.get("bestStream"):
                print("❌ 未获取到有效视频流，可能为纯图文笔记或被风控拦截")
                return False

            profile_url = f"https://www.xiaohongshu.com/user/profile/{data['userId']}"
            print(f"👩‍⚕️ 博主姓名: 【{data['author']}】", flush=True)
            print(f"🔗 博主主页: {profile_url}", flush=True)
            print(f"🎬 视频标题: {data['title'] or '(纯标题无文本)'}", flush=True)
            print(f"⏱ 视频时长: {data['videoDuration']}s", flush=True)

            clean_title = sanitize_filename(data["title"] or "小红书配药实操")
            clean_author = sanitize_filename(data["author"] or "xhs_user")
            folder_name = f"xhs_{note_id} - {clean_title} - {clean_author}"
            target_dir = DEFAULT_DOWNLOAD_DIR / folder_name
            target_dir.mkdir(parents=True, exist_ok=True)

            video_file = target_dir / f"{note_id}.mp4"
            info_file = target_dir / f"{note_id}.info.json"
            cover_file = target_dir / "cover.jpg"
            frame_file = target_dir / "frame_sample.jpg"

            best_stream = data["bestStream"]
            meta = {
                "platform": "xiaohongshu",
                "id": note_id,
                "title": data["title"],
                "uploader": data["author"],
                "uploader_id": data["userId"],
                "uploader_url": profile_url,
                "duration": data["videoDuration"],
                "description": data["desc"],
                "url": pc_url,
                "short_url": raw_url,
                "stream_info": best_stream,
            }
            info_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

            # Cover
            if data.get("coverUrl") and not cover_file.exists():
                try:
                    req_c = urllib.request.Request(data["coverUrl"], headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req_c, timeout=15) as r, open(cover_file, "wb") as fc:
                        fc.write(r.read())
                except Exception:
                    pass

            # Video
            if video_file.exists() and video_file.stat().st_size > 1024 * 500:
                mb = video_file.stat().st_size / (1024 * 1024)
                print(f"📦 本地已存在该视频，跳过下载 ({mb:.2f} MB)", flush=True)
            else:
                stream_url = best_stream["url"]
                mb_est = (best_stream.get("size") or 0) / (1024 * 1024)
                print(f"⬇️ 正在下载高清原画视频流 (~{mb_est:.1f} MB)...", flush=True)
                part_path = video_file.with_suffix(".mp4.part")
                req_v = urllib.request.Request(stream_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://www.xiaohongshu.com/",
                })
                with urllib.request.urlopen(req_v, timeout=60) as resp, open(part_path, "wb") as fv:
                    while True:
                        chunk = resp.read(512 * 1024)
                        if not chunk:
                            break
                        fv.write(chunk)
                if part_path.exists():
                    part_path.replace(video_file)

                mb = video_file.stat().st_size / (1024 * 1024)
                print(f"🎉 视频下载成功！大小: {mb:.2f} MB", flush=True)

            # Frame extraction
            seek_secs = min(max(data["videoDuration"] * 0.25, 5.0), 30.0) if data["videoDuration"] >= 10 else 1.0
            seek_time = f"{int(seek_secs // 3600):02d}:{int((seek_secs % 3600) // 60):02d}:{int(seek_secs % 60):02d}"
            subprocess.run(
                ["ffmpeg", "-y", "-ss", seek_time, "-i", str(video_file), "-vframes", "1", "-q:v", "2", str(frame_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"🖼 动作抽样帧提取完成: {frame_file.name}", flush=True)
            print(f"📁 归档目录: {target_dir}", flush=True)
            return True
        finally:
            await page.close()
            await context.close()


if __name__ == "__main__":
    url_arg = sys.argv[1] if len(sys.argv) > 1 else "https://xhslink.cn/o/1PzelvwO8vO"
    asyncio.run(download_note(url_arg))
