"""Collect Bilibili search metadata without downloading videos."""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import urllib.parse
import urllib.request
from .manifest import append_candidates


BVID = re.compile(r"BV[0-9A-Za-z]{10}")
EXCLUDED = ("ppt", "理论", "试题", "考试", "题库", "动画", "游戏", "中药", "兽医", "宠物")
ACTION_TERMS = ("配药", "抽药", "抽吸", "配液", "静配", "安瓿", "西林瓶", "药液", "药瓶")
VIEW_TERMS = ("第一视角", "pov", "沉浸式", "身临其境", "手部", "手持", "头戴")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"


def fetch_bilibili_search(keyword: str) -> list[dict]:
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com"}
    url = f"https://api.bilibili.com/x/web-interface/wbi/search/type?search_type=video&keyword={urllib.parse.quote(keyword)}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code") == 0:
            return data.get("data", {}).get("result", [])
    except Exception:
        pass
    return []


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


def search(keywords_path: Path, candidates_path: Path, limit: int, cookies_from_browser: str | None = None,
           cookies_file: Path | None = None) -> tuple[int, int]:
    keywords = load_keywords(keywords_path)
    if not keywords:
        raise ValueError("关键词文件为空")
    added = 0
    failures = 0
    consecutive_412 = 0
    for keyword in keywords:
        print(f"搜索：{keyword}", flush=True)
        command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-flat-playlist",
                   "--skip-download", "--dump-single-json", "--sleep-requests", "0.5",
                   "--retry-sleep", "extractor:linear=3:9", f"bilisearch{limit}:{keyword}"]
        if cookies_from_browser:
            command[3:3] = ["--cookies-from-browser", cookies_from_browser]
        elif cookies_file:
            command[3:3] = ["--cookies", str(cookies_file)]
        found = []
        search_error = ""
        for attempt in range(3):
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            parse_error = ""
            try:
                entries = json.loads(result.stdout).get("entries") or []
            except (ValueError, AttributeError) as error:
                entries = []
                parse_error = f"搜索结果解析失败：{error}"
            found.extend(row for entry in entries if isinstance(entry, dict) if (row := candidate(entry, keyword)))
            search_error = (result.stderr.strip() or f"yt-dlp 退出码 {result.returncode}") if result.returncode or "ERROR:" in result.stderr else ""
            if not search_error and any(entry is None for entry in entries):
                search_error = "部分视频元数据获取失败"
            search_error = search_error or parse_error

            # 若遇到 412 错误且未找到条目，尝试官方搜索直连兜底
            if "412" in search_error and not found:
                native_results = fetch_bilibili_search(keyword)
                if native_results:
                    for item in native_results:
                        bvid = item.get("bvid") or ""
                        title = re.sub(r"<[^>]+>", "", item.get("title", "")).strip()
                        pic = item.get("pic", "")
                        if pic.startswith("//"):
                            pic = "https:" + pic
                        c = candidate({
                            "id": bvid,
                            "title": title,
                            "uploader": item.get("author", ""),
                            "duration": item.get("duration", ""),
                            "thumbnail": pic
                        }, keyword)
                        if c:
                            found.append(c)
                    if found:
                        search_error = ""
                        break

            if "412" not in search_error or attempt == 2:
                break
            delay = 3 * (attempt + 1)
            print(f"B 站返回 412；{delay} 秒后重试：{keyword}（{attempt + 1}/2）", file=sys.stderr, flush=True)
            time.sleep(delay)
        added += append_candidates(candidates_path, found)
        if search_error:
            failures += 1
            print(f"搜索未完全成功：{keyword}；已保留可用候选；{search_error}", file=sys.stderr)
            consecutive_412 = consecutive_412 + 1 if "412" in search_error else 0
            if consecutive_412 >= 2:
                print("连续两个关键词被 B 站返回 412；已停止本轮搜索，请检查登录状态或稍后重试。", file=sys.stderr)
                break
        else:
            consecutive_412 = 0
    print(f"搜索结束：新增 {added} 条候选，失败关键词 {failures} 个；候选文件：{candidates_path}")
    return added, failures
