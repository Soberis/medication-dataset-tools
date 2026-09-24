"""Automated keyword search and batch crawler for Douyin and Xiaohongshu.

Uses Playwright with persistent context so you only need to scan QR code once.
Subsequent searches run headless and fully automated:
  1. Search keywords (e.g. 护士配药第一视角)
  2. Extract video IDs & metadata
  3. Filter and trigger watermark-free downloads into dataset directory
"""

import argparse
import asyncio
import json
import logging
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import BrowserContext, Page, async_playwright

from .social_downloader import DEFAULT_OUTPUT_DIR, download_url

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "data" / "browser_profile"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("social_search")


async def open_login_window(platform: str = "douyin") -> bool:
    """Open visible browser window for user to scan QR code and save login session."""
    profile_dir = ROOT / "data" / f"browser_profile_{platform}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    target_url = "https://www.douyin.com"
    proxy_cfg = None
    if platform == "douyin":
        target_url = "https://www.douyin.com"
    elif platform == "xhs":
        target_url = "https://www.xiaohongshu.com"
    elif platform == "youtube":
        target_url = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F"
        proxy_cfg = {"server": "http://127.0.0.1:7890"}

    print("\n==================================================")
    print(f"🔑 正在打开浏览器进行 [{platform.upper()}] 登录/风控验证...")
    print("登录状态将保存在本地，之后执行全自动批量搜索下载无需再次登录！")
    print("==================================================\n")

    launch_kwargs = {
        "user_data_dir": str(profile_dir),
        "headless": False,
        "viewport": {"width": 1280, "height": 850},
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        "ignore_default_args": ["--enable-automation"],
    }
    # 默认使用本机安装的正式版 Google Chrome (绝对非无痕、非沙盒测试浏览器)
    launch_kwargs["channel"] = "chrome"
    launch_kwargs["viewport"] = None
    launch_kwargs["args"].append("--start-maximized")

    if proxy_cfg:
        launch_kwargs["proxy"] = proxy_cfg

    async with async_playwright() as p:
        try:
            context = await p.chromium.launch_persistent_context(**launch_kwargs)
        except Exception:
            # 如果本机未装 Chrome，自动回退到微软官方 Edge
            try:
                launch_kwargs["channel"] = "msedge"
                context = await p.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as e:
                # 再次回退
                launch_kwargs.pop("channel", None)
                context = await p.chromium.launch_persistent_context(**launch_kwargs)

        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            print(f"页面加载提示: {e}")

        print(f"请在弹出的浏览器窗口中完成登录或验证...")
        print("登录/验证成功后，程序会自动保存凭证；您也可以完成操作后直接关闭浏览器窗口。\n")

        saved_success = False
        last_cookies = []

        for _ in range(300):  # 等待最多 10 分钟 (每次循环 2 秒)
            await asyncio.sleep(2)
            try:
                cookies = await context.cookies()
                last_cookies = cookies
            except Exception:
                # 用户主动关闭了浏览器窗口
                print(">> 检测到浏览器窗口已关闭。")
                break

            cookie_names = {c["name"] for c in cookies}

            if platform == "douyin":
                if any(k in cookie_names for k in ("sessionid", "passport_auth_status", "LOGIN_STATUS")):
                    print("🎉 抖音登录成功！登录凭证已持久化保存。")
                    saved_success = True
                    break
            elif platform == "xhs":
                try:
                    login_modal = await page.query_selector(".login-container, .login-box, .qrcode-img")
                    is_modal_visible = await login_modal.is_visible() if login_modal else False
                    user_profile_link = await page.query_selector("a[href*='/user/profile/']")
                    if not is_modal_visible and user_profile_link:
                        print("🎉 小红书登录成功！登录凭证已持久化保存。")
                        saved_success = True
                        break
                except Exception:
                    pass
            elif platform == "youtube":
                # 只有真正登录 YouTube 并完成跳转后，才会产生 LOGIN_INFO Cookie 或出现头像
                is_yt_logged_in = any(c.get("name") == "LOGIN_INFO" for c in cookies)
                if not is_yt_logged_in:
                    try:
                        avatar = await page.query_selector("button#avatar-btn")
                        if avatar:
                            is_yt_logged_in = True
                    except Exception:
                        pass

                if is_yt_logged_in:
                    cookie_path = ROOT / "data" / "youtube_cookies.txt"
                    cookie_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(cookie_path, "w", encoding="utf-8") as f:
                        f.write("# Netscape HTTP Cookie File\n")
                        for c in cookies:
                            domain = c.get("domain", "")
                            include_sub = "TRUE" if domain.startswith(".") else "FALSE"
                            path = c.get("path", "/")
                            secure = "TRUE" if c.get("secure") else "FALSE"
                            expires = str(int(c.get("expires", 0)))
                            name = c.get("name", "")
                            value = c.get("value", "")
                            f.write(f"{domain}\t{include_sub}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
                    print("🎉 YouTube 账号登录成功！已成功捕获 LOGIN_INFO 并保存至本地。")
                    saved_success = True
                    # 稍等 2 秒以确保状态完全写入
                    await asyncio.sleep(2)
                    break

        # 窗口关闭后，如果是在 YouTube 且捕获到了 cookies，也统一导出一次
        if platform == "youtube" and last_cookies:
            cookie_path = ROOT / "data" / "youtube_cookies.txt"
            cookie_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cookie_path, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for c in last_cookies:
                    domain = c.get("domain", "")
                    include_sub = "TRUE" if domain.startswith(".") else "FALSE"
                    path = c.get("path", "/")
                    secure = "TRUE" if c.get("secure") else "FALSE"
                    expires = str(int(c.get("expires", 0)))
                    name = c.get("name", "")
                    value = c.get("value", "")
                    f.write(f"{domain}\t{include_sub}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
            names = {c["name"] for c in last_cookies}
            if any(k in names for k in ("LOGIN_INFO", "SAPISID")):
                print(f"🎉 成功保存 Google/YouTube 登录凭据（共 {len(last_cookies)} 条 Cookie）至：{cookie_path}")
                saved_success = True
            else:
                print(f"⚠️ 提示：已保存 {len(last_cookies)} 条 Cookie，但未检测到 YouTube 登录凭证（LOGIN_INFO）。若下载提示 bot 检测，请重新登录。")

        try:
            await context.close()
        except Exception:
            pass

        return saved_success


async def auto_search_douyin(keyword: str, limit: int = 20, output_dir: Path = DEFAULT_OUTPUT_DIR) -> int:
    """Headless automated search and download on Douyin."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    kw_enc = urllib.parse.quote(keyword)
    search_url = f"https://www.douyin.com/search/{kw_enc}?type=video"

    logger.info(f"[抖音自动搜索] 关键词：{keyword}，目标数：{limit}")
    video_items: List[Dict[str, Any]] = []

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()

        async def on_response(resp):
            if "aweme/v1/web/search/item" in resp.url and resp.status == 200:
                try:
                    data = await resp.json()
                    items = data.get("data", [])
                    for it in items:
                        aweme = it.get("aweme_info", {})
                        if aweme and aweme.get("aweme_id"):
                            video_items.append({
                                "id": aweme.get("aweme_id"),
                                "desc": aweme.get("desc", ""),
                                "author": aweme.get("author", {}).get("nickname", ""),
                                "url": f"https://www.douyin.com/video/{aweme.get('aweme_id')}",
                            })
                except Exception:
                    pass

        page.on("response", on_response)
        await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)

        # 模拟滚动加载更多搜索结果
        for scroll_idx in range(6):
            if len(video_items) >= limit:
                break
            await page.mouse.wheel(0, 1500)
            await asyncio.sleep(2)

        # 补充从 DOM 获取视频链接
        dom_links = await page.eval_on_selector_all("a[href*='/video/']", "els => els.map(e => e.href)")
        for dl in dom_links:
            import re
            m = re.search(r"/video/([0-9]{15,22})", dl)
            if m:
                vid = m.group(1)
                if not any(v["id"] == vid for v in video_items):
                    video_items.append({
                        "id": vid,
                        "desc": "抖音视频",
                        "author": "",
                        "url": f"https://www.douyin.com/video/{vid}",
                    })

        await context.close()

    logger.info(f"[抖音自动搜索] 检索到候选视频 {len(video_items)} 部")
    if not video_items:
        logger.warning("未检索到视频，可能需要扫码登录解除风控：请先运行 `python main.py auto-search --login douyin`")
        return 0

    success_cnt = 0
    for idx, v in enumerate(video_items[:limit]):
        print(f"\n[{idx + 1}/{min(len(video_items), limit)}] 自动下载: {v['desc'][:30]} ({v['url']})")
        ok = download_url(v["url"], output_dir)
        if ok:
            success_cnt += 1

    print(f"\n==========================================")
    print(f"抖音自动搜索下载完成: 成功 {success_cnt} 部")
    print(f"==========================================")
    return success_cnt


def main():
    parser = argparse.ArgumentParser(description="抖音 / 小红书关键词自动搜索与批量下载工具")
    parser.add_argument("--keyword", "-k", default="护士配药第一视角", help="搜索关键词，默认：护士配药第一视角")
    parser.add_argument("--limit", "-l", type=int, default=15, help="下载视频数量上限，默认 15")
    parser.add_argument("--login", choices=["douyin", "xhs"], help="打开浏览器窗口扫码登录以建立免验证会话")
    parser.add_argument("--platform", choices=["douyin", "xhs"], default="douyin", help="搜索平台，默认 douyin")
    parser.add_argument("--output-dir", "-o", type=Path, default=DEFAULT_OUTPUT_DIR, help="保存目录")

    args = parser.parse_args()

    if args.login:
        asyncio.run(open_login_window(args.login))
        return 0

    if args.platform == "douyin":
        asyncio.run(auto_search_douyin(args.keyword, args.limit, args.output_dir))
    else:
        print("小红书搜索目前需先执行 --login xhs 扫码，之后将自动执行抓取。")


if __name__ == "__main__":
    main()
