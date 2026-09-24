"""Cross-Platform Video Deduplication Tool for Medication Preparation Dataset.

Features:
  1. Metadata Filter: Fast pre-screening by video duration (tolerance <= 1.0s) and sanitized title similarity.
  2. Visual pHash Filter: Frame-based DCT Perceptual Hashing (samples frames at 15%, 50%, 85%).
     Detects identical physical operations even under different compressions, bitrates, resolutions, or titles.
  3. Quality-First Resolution: Compares resolution and file size/bitrate, keeping the superior video stream
     while merging metadata tags into `cross_platform_sources`.

Usage:
  python tools/dedup_cross_platform.py --scan               # Only scan and output duplicate report
  python tools/dedup_cross_platform.py --merge-dry-run       # Simulate quality-first merge
  python tools/dedup_cross_platform.py --auto-merge          # Execute merge (moves duplicate to .duplicates_trash)
"""

import argparse
import difflib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import cv2
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dedup_cross_platform")

DEFAULT_DATASET_DIR = Path.home() / "Downloads" / "第一人称配药实操视频"


def sanitize_text(text: str) -> str:
    """Strip hashtags, special symbols, and spaces for pure text comparison."""
    text = re.sub(r"#[^#\s]+", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fa5]+", "", text)
    return text.lower().strip()


def text_similarity(s1: str, s2: str) -> float:
    """Calculate SequenceMatcher similarity between two strings."""
    c1 = sanitize_text(s1)
    c2 = sanitize_text(s2)
    if not c1 or not c2:
        return 0.0
    return difflib.SequenceMatcher(None, c1, c2).ratio()


def compute_phash_from_frame(img: np.ndarray, hash_size: int = 8, highfreq_factor: int = 4) -> np.ndarray:
    """Compute 64-bit DCT perceptual hash for an image frame."""
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img
    dim = hash_size * highfreq_factor
    resized = cv2.resize(gray, (dim, dim), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(resized))
    dct_low = dct[:hash_size, :hash_size]
    # Exclude DC term (0, 0)
    med = np.median(dct_low[1:, 1:])
    return (dct_low > med).flatten()


def hamming_distance(hash1: np.ndarray, hash2: np.ndarray) -> int:
    """Compute Hamming distance between two boolean hash vectors."""
    return int(np.count_nonzero(hash1 != hash2))


def extract_video_keyframes(video_path: Path, ratios: Tuple[float, ...] = (0.15, 0.50, 0.85)) -> List[np.ndarray]:
    """Extract frames at given relative timestamps."""
    frames = []
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return frames

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return frames

    for r in ratios:
        target_frame_idx = min(int(total_frames * r), total_frames - 1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
        ret, frame = cap.read()
        if ret and frame is not None:
            frames.append(frame)
    cap.release()
    return frames


class VideoRecord:
    def __init__(self, folder: Path):
        self.folder = folder
        self.folder_name = folder.name
        self.video_file: Optional[Path] = None
        self.info_file: Optional[Path] = None
        self.meta: Dict[str, Any] = {}
        self.duration: float = 0.0
        self.title: str = ""
        self.author: str = ""
        self.platform: str = "unknown"
        self.width: int = 0
        self.height: int = 0
        self.file_size_bytes: int = 0
        self.bitrate_kbps: float = 0.0
        self.phashes: List[np.ndarray] = []

        self._load()

    def _load(self):
        mp4_files = list(self.folder.glob("*.mp4"))
        if mp4_files:
            self.video_file = mp4_files[0]
            self.file_size_bytes = self.video_file.stat().st_size

        info_files = list(self.folder.glob("*.info.json"))
        if info_files:
            self.info_file = info_files[0]
            try:
                self.meta = json.loads(self.info_file.read_text(encoding="utf-8"))
            except Exception:
                self.meta = {}

        self.title = self.meta.get("title") or self.folder_name
        self.author = (
            self.meta.get("uploader")
            or self.meta.get("author")
            or (self.meta.get("owner", {}).get("name") if isinstance(self.meta.get("owner"), dict) else "")
            or ""
        )
        self.duration = float(self.meta.get("duration") or 0.0)
        self.platform = self.meta.get("platform") or ""
        if not self.platform:
            if self.folder_name.startswith("douyin_"):
                self.platform = "douyin"
            elif self.folder_name.startswith("xhs_"):
                self.platform = "xiaohongshu"
            elif self.folder_name.startswith("BV"):
                self.platform = "bilibili"
            elif self.folder_name.startswith("yt_"):
                self.platform = "youtube"

        # Read video resolution and duration if not in meta
        if self.video_file and (self.duration <= 0 or self.width <= 0):
            try:
                cap = cv2.VideoCapture(str(self.video_file))
                if cap.isOpened():
                    self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    if self.duration <= 0 and frame_count > 0:
                        self.duration = frame_count / fps
                    cap.release()
            except Exception:
                pass

        if self.duration > 0 and self.file_size_bytes > 0:
            self.bitrate_kbps = (self.file_size_bytes * 8) / (self.duration * 1000)

    def compute_fingerprints(self):
        """Extract keyframes and compute perceptual hashes."""
        if not self.video_file or self.phashes:
            return
        frames = extract_video_keyframes(self.video_file)
        for f in frames:
            self.phashes.append(compute_phash_from_frame(f))


def find_duplicates(records: List[VideoRecord], max_hamming: int = 5, duration_tol: float = 1.2) -> List[Dict[str, Any]]:
    """Scan and match cross-platform or intra-platform duplicates."""
    duplicates = []
    n = len(records)
    logger.info(f"正在进行双重对比（元数据初筛 + 关键帧视觉 pHash），共 {n} 个视频...")

    for i in range(n):
        r1 = records[i]
        if not r1.video_file:
            continue

        for j in range(i + 1, n):
            r2 = records[j]
            if not r2.video_file:
                continue

            # 1. Duration check
            dur_diff = abs(r1.duration - r2.duration)
            if r1.duration > 0 and r2.duration > 0 and dur_diff > duration_tol:
                # Durations differ significantly -> cannot be same clip
                continue

            # 2. Text similarity
            sim = text_similarity(r1.title, r2.title)

            # 3. Visual pHash check if duration matches or titles match
            r1.compute_fingerprints()
            r2.compute_fingerprints()

            visual_match = False
            avg_dist = 999
            if r1.phashes and r2.phashes and len(r1.phashes) == len(r2.phashes):
                distances = [hamming_distance(h1, h2) for h1, h2 in zip(r1.phashes, r2.phashes)]
                avg_dist = sum(distances) / len(distances)
                # Max allowed distance per frame is 6, or average distance <= 4
                if max(distances) <= max_hamming or avg_dist <= 4.0:
                    visual_match = True

            # Decision rule
            is_dup = False
            reason = ""
            if visual_match:
                is_dup = True
                reason = f"视觉 pHash 高度匹配 (平均汉明距离={avg_dist:.1f}, 时长差={dur_diff:.1f}s)"
            elif dur_diff <= 0.8 and sim >= 0.75:
                is_dup = True
                reason = f"时长与标题高度重合 (时长差={dur_diff:.1f}s, 标题相似度={sim*100:.1f}%)"

            if is_dup:
                # Decide which one is superior quality
                score1 = (r1.width * r1.height) * 1.0 + (r1.bitrate_kbps * 50)
                score2 = (r2.width * r2.height) * 1.0 + (r2.bitrate_kbps * 50)
                primary, secondary = (r1, r2) if score1 >= score2 else (r2, r1)

                duplicates.append({
                    "primary": primary,
                    "secondary": secondary,
                    "reason": reason,
                    "avg_hamming": avg_dist,
                    "duration_diff": dur_diff,
                    "title_sim": sim,
                })

    return duplicates


def execute_merge(duplicate_pairs: List[Dict[str, Any]], dry_run: bool = True, dataset_dir: Path = DEFAULT_DATASET_DIR):
    """Merge duplicate pairs, retaining the primary (higher quality) video."""
    trash_dir = dataset_dir / ".duplicates_trash"
    if not dry_run:
        trash_dir.mkdir(parents=True, exist_ok=True)

    for item in duplicate_pairs:
        p: VideoRecord = item["primary"]
        s: VideoRecord = item["secondary"]

        logger.info("=" * 60)
        logger.info(f"【发现重复样本】: {item['reason']}")
        logger.info(f"  [保留高画质版本] ({p.platform}) {p.folder_name} [{p.width}x{p.height}, {p.file_size_bytes/1024/1024:.2f}MB, 码率: {p.bitrate_kbps:.0f}kbps]")
        logger.info(f"  [拟清理冗余版本] ({s.platform}) {s.folder_name} [{s.width}x{s.height}, {s.file_size_bytes/1024/1024:.2f}MB, 码率: {s.bitrate_kbps:.0f}kbps]")

        if dry_run:
            logger.info("  -> [DRY-RUN 演练模式] 未做任何文件变动")
        else:
            # Update primary's info.json with merged sources
            if p.info_file and p.info_file.exists():
                sources = p.meta.get("cross_platform_sources", [p.platform])
                if s.platform not in sources:
                    sources.append(s.platform)
                p.meta["cross_platform_sources"] = sources
                p.meta["merged_duplicates"] = p.meta.get("merged_duplicates", [])
                p.meta["merged_duplicates"].append({
                    "folder": s.folder_name,
                    "platform": s.platform,
                    "title": s.title,
                    "duration": s.duration,
                    "original_meta": s.meta,
                })
                p.info_file.write_text(json.dumps(p.meta, ensure_ascii=False, indent=2), encoding="utf-8")

            # Move secondary to trash
            dest = trash_dir / s.folder_name
            if s.folder.exists():
                shutil.move(str(s.folder), str(dest))
                logger.info(f"  -> 已安全移至回收站：{dest}")


def main():
    parser = argparse.ArgumentParser(description="第一人称配药视频跨平台排重与视觉哈希检测工具")
    parser.add_argument("--dir", "-d", type=Path, default=DEFAULT_DATASET_DIR, help="数据集目录路径")
    parser.add_argument("--scan", action="store_true", help="仅扫描并输出重复报告")
    parser.add_argument("--merge-dry-run", action="store_true", help="模拟演练画质择优合并")
    parser.add_argument("--auto-merge", action="store_true", help="正式执行合并（冗余项移至 .duplicates_trash）")
    args = parser.parse_args()

    dataset_dir = args.dir
    if not dataset_dir.exists():
        logger.error(f"数据集目录不存在：{dataset_dir}")
        sys.exit(1)

    folders = [f for f in dataset_dir.iterdir() if f.is_dir() and not f.name.startswith(".")]
    logger.info(f"正在载入数据集目录：{dataset_dir} (共 {len(folders)} 个视频条目)")

    records = [VideoRecord(f) for f in folders if (f / f"{f.name.split(' - ')[0].replace('douyin_', '').replace('xhs_', '')}.mp4").exists() or list(f.glob("*.mp4"))]
    logger.info(f"有效视频文件数: {len(records)}")

    duplicates = find_duplicates(records)
    logger.info(f"扫描完毕！共检测出 {len(duplicates)} 组重复样本。")

    if not duplicates:
        print("\n🎉 完美！当前数据集中 0 重复样本，所有视频均为独立实操！\n")
        return

    if args.auto_merge:
        execute_merge(duplicates, dry_run=False, dataset_dir=dataset_dir)
    elif args.merge_dry_run:
        execute_merge(duplicates, dry_run=True, dataset_dir=dataset_dir)
    else:
        for idx, item in enumerate(duplicates, 1):
            p: VideoRecord = item["primary"]
            s: VideoRecord = item["secondary"]
            print(f"\n[{idx}] 发现重复 ({item['reason']}):")
            print(f"    保留: [{p.platform}] {p.folder_name} ({p.file_size_bytes/1024/1024:.2f}MB, {p.duration:.1f}s)")
            print(f"    重复: [{s.platform}] {s.folder_name} ({s.file_size_bytes/1024/1024:.2f}MB, {s.duration:.1f}s)")


if __name__ == "__main__":
    main()
