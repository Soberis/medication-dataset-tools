"""第一人称配药视频全量筛查与质量核验工具 (POV & Hands Verification).

全量扫描两处下载目录中的所有视频样本：
  1. D:/下载/第一人称配药实操视频 (及 D:/下载)
  2. C:/Users/<User>/Downloads/第一人称配药实操视频

对每个样本进行多维核验：
  - 语义与标题/文案核验（剔除 PPT、非临床生活日常、宠物、纯口播、考编理论等）
  - 视频视觉抽样帧核验（基于 OpenCV 分析双手/医用手套占比、幻灯片/屏幕特征、画面纵横比）
  - 自动输出分类筛查清单供人工快速终审，防止不合格视频上传入库。
"""

import csv
import json
import logging
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pov_audit")

ROOTS = [
    Path("D:/下载/第一人称配药实操视频"),
    Path("D:/下载"),
    Path.home() / "Downloads" / "第一人称配药实操视频",
]

# 1. 负向非配药/非实操关键词（命中则强烈提示非实操）
NEGATIVE_KEYWORDS = [
    ("ppt", "PPT课件/幻灯片分享"),
    ("办公技巧", "电脑办公教程"),
    ("换被子", "非配药日常(整理病床)"),
    ("铺床", "非配药日常(整理病床)"),
    ("毛孩子", "宠物相关视频"),
    ("宠物", "宠物相关视频"),
    ("狗狗", "宠物相关视频"),
    ("下班后", "护士生活日常"),
    ("下班日常", "护士生活日常"),
    ("逛街", "生活休闲日常"),
    ("吃播", "饮食生活日常"),
    ("外卖", "饮食生活日常"),
    ("租房", "生活日常"),
    ("面试", "面试/求职经验"),
    ("考编", "考编理论复习"),
    ("规培", "规培考试/理论分享"),
    ("题库", "理论刷题"),
    ("刷题", "理论刷题"),
    ("搞笑", "剧情娱乐短剧"),
    ("段子", "娱乐表演段子"),
    ("演绎", "剧情演绎表演"),
    ("护肤", "美妆护肤日常"),
    ("爱用物", "好物推荐/带货"),
    ("开箱", "物品开箱日常"),
    ("休学", "个人经历故事口播"),
    ("聊天", "纯人像口播聊天"),
    ("访谈", "对话采访/纪录"),
    ("置港倒计时", "患者就医记录"),
]

# 2. 正向第一人称配药与手部实操关键词
POSITIVE_KEYWORDS = [
    "配药", "配液", "溶药", "加药", "抽药", "摆药", "抽吸", "排气",
    "一镜到底", "沉浸式", "第一视角", "第一人称", "安瓿", "西林瓶",
    "粉针", "生理盐水", "注射器", "穿刺", "留置针", "皮试", "扎针",
    "输液", "挂水", "静脉", "推注", "抽血", "无菌", "治疗台"
]


def compute_hand_ratio(img: np.ndarray) -> float:
    """Compute ratio of pixels matching bare hands, cyan/blue gloves, or purple gloves."""
    if img is None:
        return 0.0
    h, w, _ = img.shape
    if h == 0 or w == 0:
        return 0.0

    # Operational area: lower 65% of screen
    roi = img[int(h * 0.35):, :]
    roi_h, roi_w, _ = roi.shape
    if roi_h == 0 or roi_w == 0:
        return 0.0

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    ycrcb = cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb)

    # 1. Bare skin tone (YCrCb)
    mask_skin = (ycrcb[:, :, 1] >= 133) & (ycrcb[:, :, 1] <= 173) & (ycrcb[:, :, 2] >= 77) & (ycrcb[:, :, 2] <= 127)
    # 2. Blue / cyan nitrile gloves (common in medical ICU/cleanrooms)
    mask_blue = (hsv[:, :, 0] >= 85) & (hsv[:, :, 0] <= 130) & (hsv[:, :, 1] >= 45) & (hsv[:, :, 2] >= 40)
    # 3. Purple nitrile gloves
    mask_purple = (hsv[:, :, 0] >= 130) & (hsv[:, :, 0] <= 165) & (hsv[:, :, 1] >= 35) & (hsv[:, :, 2] >= 40)

    combined_hands = mask_skin | mask_blue | mask_purple
    return float(np.sum(combined_hands) / (roi_h * roi_w))


def cv2_imread_unicode(file_path: Path) -> Optional[np.ndarray]:
    """Safe Unicode path reader for OpenCV on Windows."""
    try:
        if not file_path.exists():
            return None
        data = np.fromfile(str(file_path), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def analyze_sample_frames(folder: Path) -> Dict[str, Any]:
    """Fast frame analysis prioritizing pre-extracted frames (frame_sample.jpg, cover.jpg)."""
    result = {
        "width": 0,
        "height": 0,
        "aspect_ratio": "vertical",
        "hand_ratio": 0.0,
        "is_static_ppt": False,
    }

    frame_img_path = folder / "frame_sample.jpg"
    cover_img_path = folder / "cover.jpg"

    img = None
    if frame_img_path.exists():
        img = cv2_imread_unicode(frame_img_path)
    if img is None and cover_img_path.exists():
        img = cv2_imread_unicode(cover_img_path)

    if img is not None:
        h, w, _ = img.shape
        result["width"] = w
        result["height"] = h
        result["aspect_ratio"] = "vertical" if h >= w else "horizontal"
        result["hand_ratio"] = compute_hand_ratio(img)

        # Check for PPT / solid computer screen
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        std_val = float(np.std(gray))
        if std_val < 18.0 and result["hand_ratio"] < 0.05:
            result["is_static_ppt"] = True
        return result
    return result


def audit_dataset():
    logger.info("==================================================")
    logger.info("🚀 启动临床第一视角双手配药视频质量全量审计")
    logger.info("==================================================")

    seen = set()
    all_folders = []
    for r in ROOTS:
        if r.exists():
            for f in sorted(r.iterdir()):
                if f.is_dir() and not f.name.startswith(".") and f.name not in seen:
                    mp4s = list(f.glob("*.mp4"))
                    if mp4s:
                        seen.add(f.name)
                        all_folders.append(f)

    logger.info(f"两处下载路径共扫描到 {len(all_folders)} 个独立视频条目。正在进行多维度快速核验...")

    results = []

    for idx, folder in enumerate(all_folders, 1):
        # 1. 提取元数据
        info_files = list(folder.glob("*.info.json"))
        author = "未知"
        title = ""
        desc = ""
        duration = 0.0
        platform = "未知"

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
                desc = data.get("description") or data.get("desc") or ""
                duration = data.get("duration") or 0.0
                author = data.get("uploader") or data.get("author") or author
                if "owner" in data and isinstance(data["owner"], dict):
                    author = data["owner"].get("name", author)
            except Exception:
                pass

        if not title:
            parts = folder.name.split(" - ")
            title = parts[1] if len(parts) >= 2 else folder.name
            if len(parts) >= 3 and author == "未知":
                author = parts[-1]

        full_text = f"{title} {desc}".lower()

        # 2. 语义关键词检测
        matched_negatives = []
        for kw, reason in NEGATIVE_KEYWORDS:
            if kw in full_text:
                matched_negatives.append(f"{kw} ({reason})")

        matched_positives = [kw for kw in POSITIVE_KEYWORDS if kw in full_text]

        # 3. 视觉分析
        vf = analyze_sample_frames(folder)
        hand_pct = vf.get("hand_ratio", 0.0) * 100
        aspect = vf.get("aspect_ratio", "vertical")

        # 4. 科学综合判定逻辑
        status = "🟢 合格"
        reasons = []

        if matched_negatives:
            status = "🔴 建议剔除"
            reasons.append("命中非实操文案: " + "、".join(matched_negatives))

        if vf.get("is_static_ppt"):
            status = "🔴 建议剔除"
            reasons.append("画面静止/疑似电脑幻灯片(PPT)")

        if not matched_positives and hand_pct < 5.0:
            status = "🔴 建议剔除"
            reasons.append(f"既无配药动作词且未检出有效手部操作(手部占比仅 {hand_pct:.1f}%)")
        elif hand_pct < 3.0 and status != "🔴 建议剔除":
            status = "🟡 需人工复核"
            reasons.append(f"画面双手特征占比极低({hand_pct:.1f}%)，需确认是否为第一视角或远景")

        if duration > 0 and duration < 6.0:
            if status == "🟢 合格":
                status = "🟡 需人工复核"
            reasons.append(f"视频时长过短({duration:.1f}s)，可能非完整配药过程")

        if aspect == "horizontal" and status == "🟢 合格" and hand_pct < 15.0:
            status = "🟡 需人工复核"
            reasons.append("横屏拍摄且手部特写占比偏低，需核对是否为第三人称远景示范")

        if not reasons:
            reasons.append("符合第一视角沉浸式双手配药操作规范")

        results.append({
            "folder": folder.name,
            "author": author,
            "platform": platform,
            "status": status,
            "duration": f"{duration:.1f}s" if duration else "--",
            "aspect": "竖屏(9:16)" if aspect == "vertical" else "横屏(16:9)",
            "hand_pct": f"{hand_pct:.1f}%",
            "title": title[:60],
            "reason": "；".join(reasons),
            "rel_path": str(folder),
        })

    # 输出到 CSV 档案供用户终审
    out_csv = Path("data/非第一人称或无双手视频筛查表.csv")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["序号", "审核判定", "博主名字", "涉及平台", "视频时长", "画面规格", "手部特征占比", "视频标题", "筛查建议原因", "本地文件夹名称"])
        for i, r in enumerate(results, 1):
            writer.writerow([
                i,
                r["status"],
                r["author"],
                r["platform"],
                r["duration"],
                r["aspect"],
                r["hand_pct"],
                r["title"],
                r["reason"],
                r["folder"],
            ])

    # 统计分类
    stats = defaultdict(int)
    for r in results:
        stats[r["status"]] += 1

    logger.info("==================================================")
    logger.info(f"✅ 全量筛查完成！已输出完整筛查表至：{out_csv}")
    logger.info(f"📊 汇总统计（共 {len(results)} 部视频）：")
    logger.info(f"   🟢 符合要求（第一视角沉浸双手）: {stats['🟢 合格']} 部")
    logger.info(f"   🟡 建议人工复核（边界/特殊/低手部）: {stats['🟡 需人工复核']} 部")
    logger.info(f"   🔴 建议剔除（非第一人称/无双手/生活PPT）: {stats['🔴 建议剔除']} 部")
    logger.info("==================================================")

    return results


if __name__ == "__main__":
    audit_dataset()
