"""Download manually selected Bilibili videos."""

import logging
import re
import subprocess
import sys
from pathlib import Path

from .manifest import read_candidates


BVID = re.compile(r"BV[0-9A-Za-z]{10}\Z")


def download(candidates_path: Path, data_dir: Path) -> tuple[int, int]:
    rows = read_candidates(candidates_path)
    selected = [row for row in rows if row["selected"].strip() == "1"]
    data_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("download")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(data_dir / "download.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    success = failed = 0
    for row in selected:
        bvid = row["bvid"].strip()
        url = f"https://www.bilibili.com/video/{bvid}"
        if not BVID.fullmatch(bvid) or row["url"].strip().rstrip("/") != url:
            failed += 1
            logger.error("BV 或 URL 无效：%s", bvid)
            print(f"失败：{bvid}，BV 或 URL 无效", file=sys.stderr)
            continue
        command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
                   "--continue", "--no-overwrites", "--write-info-json", "--write-thumbnail",
                   "--download-archive", str(data_dir / "downloaded.txt"),
                   "-f", "bv*[height<=1080]+ba/b[height<=1080]",
                   "--merge-output-format", "mp4", "--remux-video", "mp4",
                   "-o", str(data_dir / "videos" / bvid / f"{bvid}.%(ext)s"), url]
        print(f"下载：{bvid}", flush=True)
        result = subprocess.run(command, check=False)
        if result.returncode == 0:
            success += 1
            logger.info("完成或已在档案中：%s %s", bvid, url)
        else:
            failed += 1
            logger.error("下载失败：%s %s exit=%s", bvid, url, result.returncode)
            print(f"失败：{bvid}，退出码 {result.returncode}", file=sys.stderr)
    handler.close()
    logger.removeHandler(handler)
    print(f"下载结束：完成或跳过 {success}，失败 {failed}；日志：{data_dir / 'download.log'}")
    return success, failed
