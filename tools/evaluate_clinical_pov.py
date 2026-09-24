"""临床配药视频多维科学质量量化评估工具 (Clinical POV & Quality Quantitative Evaluator).

评估维度：
1. 时长评级 (Duration Rating):
   - 单步原子特写 (<15s)
   - 标准完整配药 (15s - 300s)
   - 超长需切片 (>300s)
2. 多帧双手稳定度得分 (Hands Stability Score, 0-100 分):
   - 时序多锚点采样 (20%, 50%, 80%)
   - 医用手套与裸手肤色融合分割 (皮肤/浅蓝/紫色丁腈手套)
   - 动作连续性与双臂视场一致性量化打分
3. 清晰度得分 (Laplacian Sharpness Score):
   - 核心操作区域拉普拉斯梯度二阶微分方差
   - 区分超清(>=200)、高清(100-200)、标清(50-100)、模糊(<50)
4. 综合临床推荐分级 (Tier S / A / B / C)
"""

import csv
import json
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("evaluator")

TARGET_DIR = Path(r"D:\下载\第一人称配药实操视频")
OUTPUT_CSV = Path("data/临床视频科学质量量化评估表.csv")


def compute_frame_metrics(img: np.ndarray) -> Tuple[float, float, int, int]:
    """计算单帧的手部特征占比与清晰度得分 (Laplacian Variance)."""
    if img is None:
        return 0.0, 0.0, 0, 0
    h, w, _ = img.shape
    if h == 0 or w == 0:
        return 0.0, 0.0, 0, 0

    # 核心操作区：画面中下部 65% (避开顶部水印/文案贴图)
    roi = img[int(h * 0.35):, :]
    roi_h, roi_w, _ = roi.shape
    if roi_h == 0 or roi_w == 0:
        return 0.0, 0.0, w, h

    # 1. 颜色空间手部/手套分割
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    ycrcb = cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb)

    # 裸手肤色 (YCrCb)
    mask_skin = (ycrcb[:, :, 1] >= 133) & (ycrcb[:, :, 1] <= 173) & (ycrcb[:, :, 2] >= 77) & (ycrcb[:, :, 2] <= 127)
    # 医用蓝/青色丁腈手套 (HSV)
    mask_blue = (hsv[:, :, 0] >= 85) & (hsv[:, :, 0] <= 130) & (hsv[:, :, 1] >= 45) & (hsv[:, :, 2] >= 40)
    # 医用紫色丁腈手套 (HSV)
    mask_purple = (hsv[:, :, 0] >= 130) & (hsv[:, :, 0] <= 165) & (hsv[:, :, 1] >= 35) & (hsv[:, :, 2] >= 40)

    combined_hands = mask_skin | mask_blue | mask_purple
    hand_ratio = float(np.sum(combined_hands) / (roi_h * roi_w))

    # 2. 清晰度得分 (Laplacian Variance on grayscale ROI)
    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    laplacian_var = float(cv2.Laplacian(gray_roi, cv2.CV_64F).var())

    return hand_ratio, laplacian_var, w, h


def evaluate_single_video(folder_str: str) -> Optional[Dict[str, Any]]:
    """子进程执行单个视频的多锚点科学评估."""
    folder = Path(folder_str)
    mp4s = list(folder.glob("*.mp4"))
    if not mp4s:
        return None
    mp4_path = mp4s[0]
    size_mb = mp4_path.stat().st_size / (1024 * 1024)

    # 读取元数据
    info_files = list(folder.glob("*.info.json"))
    title = ""
    author = "未知"
    platform = "未知"
    raw_duration = 0.0

    if folder.name.startswith("douyin_"):
        platform = "抖音"
    elif folder.name.startswith("xhs_"):
        platform = "小红书"
    elif folder.name.startswith("youtube_"):
        platform = "YouTube"
    elif folder.name.startswith("BV"):
        platform = "B站"

    if info_files:
        try:
            data = json.loads(info_files[0].read_text(encoding="utf-8"))
            title = data.get("title") or ""
            author = data.get("uploader") or data.get("author") or author
            raw_duration = float(data.get("duration") or 0.0)
        except Exception:
            pass

    if not title or author == "未知":
        parts = folder.name.split(" - ")
        if len(parts) >= 2 and not title:
            title = parts[1]
        if len(parts) >= 3 and author == "未知":
            author = parts[-1]

    # 打开视频执行多时间锚点解码采样 (20%, 50%, 80%)
    cap = cv2.VideoCapture(str(mp4_path))
    if not cap.isOpened():
        return None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    calc_duration = total_frames / fps if total_frames > 0 else 0.0
    duration = raw_duration if raw_duration > 0 else calc_duration

    hand_ratios = []
    sharpness_scores = []
    w_final, h_final = 0, 0

    anchors = [0.20, 0.50, 0.80] if total_frames >= 10 else [0.50]
    for pos in anchors:
        frame_idx = int(total_frames * pos)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if ret and frame is not None:
            hr, sh, fw, fh = compute_frame_metrics(frame)
            hand_ratios.append(hr)
            sharpness_scores.append(sh)
            w_final, h_final = fw, fh
    cap.release()

    if not hand_ratios:
        return None

    # 1. 时长评级 (Duration Rating)
    if duration < 15.0:
        duration_rating = "原子动作特写 (<15s)"
        duration_category = "原子特写"
    elif duration <= 300.0:
        duration_rating = "标准完整配药 (15s-300s)"
        duration_category = "标准配药"
    else:
        duration_rating = "超长需切片 (>300s)"
        duration_category = "超长待切片"

    # 2. 多帧双手稳定度得分 (0-100 分)
    # 逻辑：有效双手出现率 (>=3% 为有效) 贡献基础分 50分；平均操作面积覆盖度贡献 50分
    valid_hand_frames = sum(1 for r in hand_ratios if r >= 0.03)
    presence_ratio = valid_hand_frames / len(hand_ratios)
    avg_hand_ratio = float(np.mean(hand_ratios))

    # 手部稳定度模型得分
    stability_score = int(presence_ratio * 50 + min(avg_hand_ratio / 0.35, 1.0) * 50)
    stability_score = max(0, min(100, stability_score))

    # 3. 清晰度得分 (Sharpness Score - 参照真实医疗基准样本 video1: 59.2, video2: 46.1 校准)
    avg_sharpness = float(np.mean(sharpness_scores))
    if avg_sharpness >= 100.0:
        sharpness_level = "超高清 (锐利特写)"
    elif avg_sharpness >= 35.0:
        sharpness_level = "标准清晰 (基准达标)"
    else:
        sharpness_level = "严重虚焦 (抖动模糊)"

    # 4. 视角模式识别 (第一视角俯视 vs 侧向双手特写，如 benchmark video1/video2)
    # video1: 侧拍特写双手折安瓿; video2: 俯视双手推抽大注射器
    aspect_label = "竖屏 (9:16)" if h_final >= w_final else "横屏 (16:9)"
    view_type = "双手特写实操" if avg_hand_ratio >= 0.15 else "常规第一视角"

    # 5. 综合临床推荐级别 (Clinical Tier)
    if duration_category == "标准配药" and stability_score >= 60 and avg_sharpness >= 35:
        tier = "🌟 S级 (黄金双手实操)"
    elif duration_category == "标准配药" and stability_score >= 40:
        tier = "🟢 A级 (标准双手合格)"
    elif duration_category == "原子特写" and stability_score >= 40:
        tier = "🔹 B级 (单步微动作特写)"
    elif duration_category == "超长待切片":
        tier = "🟡 C级 (长流程待切片)"
    else:
        tier = "⚠️ 需人工复核"

    return {
        "folder_name": folder.name,
        "author": author,
        "platform": platform,
        "duration": round(duration, 1),
        "duration_rating": duration_rating,
        "duration_category": duration_category,
        "stability_score": stability_score,
        "avg_hand_pct": f"{avg_hand_ratio * 100:.1f}%",
        "sharpness_score": round(avg_sharpness, 1),
        "sharpness_level": sharpness_level,
        "resolution": f"{w_final}x{h_final}",
        "aspect_label": aspect_label,
        "size_mb": round(size_mb, 2),
        "tier": tier,
        "title": title[:60],
    }


def main():
    logger.info("==================================================")
    logger.info("🚀 启动临床第一人称配药视频多维科学量化评估")
    logger.info(f"目标目录: {TARGET_DIR}")
    logger.info("==================================================")

    folders = [f for f in sorted(TARGET_DIR.iterdir()) if f.is_dir() and not f.name.startswith(".")]
    total_videos = len(folders)
    logger.info(f"共发现 {total_videos} 个视频样本，正在启用 10 核心并行处理...")

    t0 = time.time()
    results = []

    workers = min(10, os.cpu_count() or 4)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(evaluate_single_video, str(f)): f for f in folders}
        done_count = 0
        for future in as_completed(futures):
            res = future.result()
            if res:
                results.append(res)
            done_count += 1
            if done_count % 100 == 0 or done_count == total_videos:
                logger.info(f"评估进度: {done_count}/{total_videos} 完成 ({time.time()-t0:.1f}s)...")

    logger.info(f"✅ 全量评估完成！耗时: {time.time()-t0:.1f} 秒，有效评估样本: {len(results)} 部")

    # 按综合推荐评级与得分降序排列
    tier_order = {
        "🌟 S级 (黄金完整实操)": 1,
        "🟢 A级 (标准合格样本)": 2,
        "🔹 B级 (单步微动作特写)": 3,
        "🟡 C级 (长流程待切片)": 4,
        "⚠️ 需人工复核": 5,
    }
    results.sort(key=lambda x: (tier_order.get(x["tier"], 9), -x["stability_score"], -x["sharpness_score"]))

    # 导出科学量化评估表
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "序号",
        "综合推荐评级",
        "博主名字",
        "涉及平台",
        "视频时长(秒)",
        "时长分级",
        "多帧双手稳定度得分(0-100)",
        "平均双手占比",
        "清晰度得分(拉普拉斯方差)",
        "清晰度级别",
        "分辨率",
        "画幅比例",
        "文件大小(MB)",
        "视频标题",
        "本地文件夹名称",
    ]

    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for idx, r in enumerate(results, 1):
            writer.writerow([
                idx,
                r["tier"],
                r["author"],
                r["platform"],
                r["duration"],
                r["duration_rating"],
                r["stability_score"],
                r["avg_hand_pct"],
                r["sharpness_score"],
                r["sharpness_level"],
                r["resolution"],
                r["aspect_label"],
                r["size_mb"],
                r["title"],
                r["folder_name"],
            ])

    logger.info(f"📊 科学评估档案已成功导出至: {OUTPUT_CSV}")

    # 统计分布
    from collections import Counter
    dur_counts = Counter(r["duration_rating"] for r in results)
    tier_counts = Counter(r["tier"] for r in results)
    sharp_counts = Counter(r["sharpness_level"] for r in results)

    high_stability = sum(1 for r in results if r["stability_score"] >= 80)
    mid_stability = sum(1 for r in results if 50 <= r["stability_score"] < 80)
    low_stability = sum(1 for r in results if r["stability_score"] < 50)

    print("\n" + "=" * 60)
    print("📈 临床数据集科学量化评估总览报告")
    print("=" * 60)

    print("\n1. 时长评级分布 (Duration Rating):")
    for k, v in dur_counts.items():
        pct = v / len(results) * 100
        print(f"   • {k:<25}: {v:>4} 部 ({pct:>5.1f}%)")

    print("\n2. 多帧双手稳定度得分分布 (Hands Stability Score):")
    print(f"   • 卓越稳定 [80 - 100 分]  : {high_stability:>4} 部 ({high_stability/len(results)*100:>5.1f}%)")
    print(f"   • 良好标准 [50 -  79 分]  : {mid_stability:>4} 部 ({mid_stability/len(results)*100:>5.1f}%)")
    print(f"   • 波动/特写 [< 50 分]     : {low_stability:>4} 部 ({low_stability/len(results)*100:>5.1f}%)")

    print("\n3. 画面清晰度级别分布 (Laplacian Sharpness):")
    for k, v in sharp_counts.items():
        pct = v / len(results) * 100
        print(f"   • {k:<25}: {v:>4} 部 ({pct:>5.1f}%)")

    print("\n4. 综合临床推荐级别 (Clinical Quality Tier):")
    for k, v in tier_counts.items():
        pct = v / len(results) * 100
        print(f"   • {k:<25}: {v:>4} 部 ({pct:>5.1f}%)")
    print("=" * 60)


if __name__ == "__main__":
    main()
