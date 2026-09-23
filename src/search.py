"""Collect Bilibili search metadata without downloading videos."""

import json
import re
import subprocess
import sys
from pathlib import Path

from .manifest import append_candidates


BVID = re.compile(r"BV[0-9A-Za-z]{10}")
EXCLUDED = ("ppt", "理论", "试题", "考试", "题库", "动画", "游戏", "中药", "兽医", "宠物")
ACTION_TERMS = ("配药", "抽药", "抽吸", "配液", "静配", "安瓿", "西林瓶", "药液", "药瓶")
VIEW_TERMS = ("第一视角", "pov", "沉浸式", "身临其境", "手部", "手持", "头戴")


def load_keywords(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig") as stream:
        return list(dict.fromkeys(line.strip() for line in stream if line.strip() and not line.lstrip().startswith("#")))


def candidate(entry: dict, keyword: str) -> dict[str, str] | None:
    title = str(entry.get("title") or "").strip()
    folded = title.casefold()
    if not title or any(term in folded for term in EXCLUDED) or not any(term in folded for term in ACTION_TERMS):
        return None
    raw = " ".join(str(entry.get(key) or "") for key in ("id", "url", "webpage_url"))
    match = BVID.search(raw)
    if not match:
        return None
    bvid = match.group()
    return {
        "selected": "0", "bvid": bvid, "title": title,
        "url": f"https://www.bilibili.com/video/{bvid}",
        "keyword": keyword, "uploader": str(entry.get("uploader") or ""),
        "duration": str(entry.get("duration") or ""),
        "title_hint": "优先预览" if any(term in folded for term in VIEW_TERMS) else "普通预览",
        "thumbnail": str(entry.get("thumbnail") or ""),
    }


def search(keywords_path: Path, candidates_path: Path, limit: int) -> tuple[int, int]:
    keywords = load_keywords(keywords_path)
    if not keywords:
        raise ValueError("关键词文件为空")
    found = []
    failures = 0
    for keyword in keywords:
        print(f"搜索：{keyword}", flush=True)
        command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-flat-playlist",
                   "--skip-download", "--dump-single-json", f"bilisearch{limit}:{keyword}"]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if result.returncode:
            failures += 1
            print(f"搜索失败：{keyword}：{result.stderr.strip() or result.returncode}", file=sys.stderr)
            continue
        try:
            entries = json.loads(result.stdout).get("entries") or []
        except (ValueError, AttributeError) as error:
            failures += 1
            print(f"搜索结果解析失败：{keyword}：{error}", file=sys.stderr)
            continue
        usable = [row for entry in entries if isinstance(entry, dict) if (row := candidate(entry, keyword))]
        found.extend(usable)
        if "ERROR:" in result.stderr or any(entry is None for entry in entries):
            failures += 1
            print(f"部分候选元数据获取失败：{keyword}：保留 {len(usable)} 条", file=sys.stderr)
    added = append_candidates(candidates_path, found)
    print(f"搜索结束：新增 {added} 条候选，失败关键词 {failures} 个；候选文件：{candidates_path}")
    return added, failures
