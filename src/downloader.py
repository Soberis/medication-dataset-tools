import json
import logging
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from .manifest import read_candidates


BVID = re.compile(r"BV[0-9A-Za-z]{10}\Z")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"


def download_bilibili_stream(bvid: str, target_dir: Path) -> bool:
    """Download video directly using Bilibili official stream API to bypass 412."""
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com"}
    target_dir.mkdir(parents=True, exist_ok=True)
    video_path = target_dir / f"{bvid}.mp4"
    if video_path.exists() and video_path.stat().st_size > 1024 * 100:
        return True
    try:
        req_view = urllib.request.Request(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", headers=headers)
        with urllib.request.urlopen(req_view, timeout=10) as resp:
            view_data = json.loads(resp.read().decode("utf-8"))
        if view_data.get("code") != 0:
            return False
        data = view_data["data"]
        aid, cid = data["aid"], data["cid"]
        (target_dir / f"{bvid}.info.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        req_play = urllib.request.Request(
            f"https://api.bilibili.com/x/player/playurl?avid={aid}&cid={cid}&qn=64&type=mp4&platform=html5",
            headers=headers,
        )
        with urllib.request.urlopen(req_play, timeout=10) as resp:
            play_data = json.loads(resp.read().decode("utf-8"))
        if play_data.get("code") != 0:
            return False
        durls = play_data.get("data", {}).get("durl") or []
        if not durls:
            return False

        temp_path = target_dir / f"{bvid}.mp4.part"
        req_stream = urllib.request.Request(durls[0]["url"], headers=headers)
        with urllib.request.urlopen(req_stream, timeout=30) as stream, open(temp_path, "wb") as out_f:
            while True:
                chunk = stream.read(1024 * 512)
                if not chunk:
                    break
                out_f.write(chunk)
        if temp_path.exists():
            temp_path.replace(video_path)
        return video_path.exists() and video_path.stat().st_size > 0
    except Exception:
        return False


def download(candidates_path: Path, output_dir: Path, cookies_from_browser: str | None = None,
             cookies_file: Path | None = None) -> tuple[int, int]:
    rows = read_candidates(candidates_path)
    selected = [row for row in rows if row["selected"].strip() == "1"]
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("download")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(output_dir / "download.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    archive_path = output_dir / "downloaded.txt"
    success = failed = 0
    for row in selected:
        bvid = row["bvid"].strip()
        url = f"https://www.bilibili.com/video/{bvid}"
        if not BVID.fullmatch(bvid) or row["url"].strip().rstrip("/") != url:
            failed += 1
            logger.error("BV 或 URL 无效：%s", bvid)
            print(f"失败：{bvid}，BV 或 URL 无效", file=sys.stderr)
            continue
        target_dir = output_dir / bvid
        target_video = target_dir / f"{bvid}.mp4"
        if target_video.exists() and target_video.stat().st_size > 1024 * 100:
            success += 1
            logger.info("本地已存在跳过：%s %s", bvid, url)
            print(f"已完成（已跳过）：{bvid}")
            continue

        command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
                   "--continue", "--no-overwrites", "--write-info-json", "--write-thumbnail",
                   "--download-archive", str(archive_path),
                   "-f", "bv*[height<=1080]+ba/b[height<=1080]",
                   "--merge-output-format", "mp4", "--remux-video", "mp4",
                   "-o", str(target_dir / f"{bvid}.%(ext)s"), url]
        if cookies_from_browser:
            command[3:3] = ["--cookies-from-browser", cookies_from_browser]
        elif cookies_file:
            command[3:3] = ["--cookies", str(cookies_file)]
        print(f"下载：{bvid}", flush=True)
        result = subprocess.run(command, check=False)
        if result.returncode == 0:
            success += 1
            logger.info("完成或已在档案中：%s %s", bvid, url)
        else:
            # 当 yt-dlp 失败（例如 412）时，自动尝试原生官方流直连
            if download_bilibili_stream(bvid, target_dir):
                success += 1
                logger.info("完成（原生直连）：%s %s", bvid, url)
                with open(archive_path, "a", encoding="utf-8") as af:
                    af.write(f"bilibili {bvid}\n")
                print(f"完成（原生直连）：{bvid}")
            else:
                failed += 1
                logger.error("下载失败：%s %s exit=%s", bvid, url, result.returncode)
                print(f"失败：{bvid}，退出码 {result.returncode}", file=sys.stderr)
    handler.close()
    logger.removeHandler(handler)
    print(f"下载结束：完成或跳过 {success}，失败 {failed}；日志：{output_dir / 'download.log'}")
    return success, failed
