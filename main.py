"""Bilibili medication video search and download CLI."""

import argparse
from pathlib import Path

from src.downloader import download
from src.search import search


ROOT = Path(__file__).resolve().parent


DEFAULT_DOWNLOAD_DIR = Path("D:/下载/第一人称配药实操视频")


def main() -> int:
    parser = argparse.ArgumentParser(description="第一人称配药实操视频采集与下载管理工具 (B站/小红书/抖音)")
    commands = parser.add_subparsers(dest="command", required=True)

    # 1. B站搜索
    search_command = commands.add_parser("search", help="搜索并追加 B 站候选")
    search_command.add_argument("--limit", type=int, default=50, help="每个关键词搜索结果数，默认 50")
    search_auth = search_command.add_mutually_exclusive_group()
    search_auth.add_argument("--cookies-from-browser", choices=("edge", "chrome", "firefox"),
                             help="可选：使用本机浏览器登录状态")
    search_auth.add_argument("--cookies-file", type=Path, help="可选：Netscape 格式 Cookie 文件")

    # 2. B站批量下载 (CSV)
    download_command = commands.add_parser("download", help="下载 candidates.csv 中 selected=1 的 B 站视频")
    download_auth = download_command.add_mutually_exclusive_group()
    download_auth.add_argument("--cookies-from-browser", choices=("edge", "chrome", "firefox"),
                               help="可选：使用本机浏览器登录状态")
    download_auth.add_argument("--cookies-file", type=Path, help="可选：Netscape 格式 Cookie 文件")
    download_command.add_argument("--output-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR,
                                  help=f"下载保存目录，默认 ({DEFAULT_DOWNLOAD_DIR})")

    # 3. 小红书 / 抖音 / YouTube / B站 单条或批量下载
    social_command = commands.add_parser("social", help="下载小红书 / 抖音 / YouTube / B站 配药第一视角视频")
    social_command.add_argument("url", nargs="?", help="分享链接或包含链接的复制文本")
    social_command.add_argument("--file", "-f", type=Path, help="文本文件路径，每行一个链接")
    social_command.add_argument("--watch", "-w", action="store_true", help="启动剪贴板监听模式，复制链接即可自动下载")
    social_command.add_argument("--cookies-file", type=Path, help="可选：Netscape 格式 Cookies 文件")
    social_command.add_argument("--output-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR,
                                help=f"下载保存目录，默认 ({DEFAULT_DOWNLOAD_DIR})")

    # 4. 抖音 / 小红书 / YouTube 自动关键词搜索爬取
    auto_command = commands.add_parser("auto-search", help="关键词自动搜索并批量下载抖音/小红书/YouTube配药视频")
    auto_command.add_argument("--keyword", "-k", default="护士配药第一视角", help="搜索关键词，默认：护士配药第一视角")
    auto_command.add_argument("--limit", "-l", type=int, default=15, help="抓取视频数上限，默认 15")
    auto_command.add_argument("--platform", choices=["douyin", "xhs", "youtube"], default="douyin", help="平台，默认 douyin")
    auto_command.add_argument("--login", choices=["douyin", "xhs", "youtube"], help="扫码/网页登录以建立免风控持久会话")
    auto_command.add_argument("--output-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR,
                              help=f"下载保存目录，默认 ({DEFAULT_DOWNLOAD_DIR})")

    args = parser.parse_args()
    if getattr(args, "cookies_file", None) and not args.cookies_file.is_file():
        parser.error(f"Cookie 文件不存在：{args.cookies_file}")
    data_dir = ROOT / "data"

    try:
        if args.command == "search":
            if args.limit < 1:
                parser.error("--limit 必须大于 0")
            _, failures = search(ROOT / "config" / "keywords.txt", data_dir / "candidates.csv", args.limit,
                                 args.cookies_from_browser, args.cookies_file)
        elif args.command == "download":
            if not (data_dir / "candidates.csv").exists():
                parser.error("请先执行 search，或创建 data/candidates.csv")
            _, failures = download(data_dir / "candidates.csv", args.output_dir,
                                   args.cookies_from_browser, args.cookies_file)
        elif args.command == "auto-search":
            import asyncio
            from src.social_search import open_login_window, auto_search_douyin
            failures = 0
            if args.login:
                asyncio.run(open_login_window(args.login))
                return 0
            if args.platform == "douyin":
                cnt = asyncio.run(auto_search_douyin(args.keyword, args.limit, args.output_dir))
                failures = 0 if cnt > 0 else 1
            elif args.platform == "youtube":
                from auto_download_youtube import auto_download_all
                cnt = auto_download_all(keywords=[args.keyword], limit_per_kw=args.limit, total_max=args.limit, output_dir=args.output_dir)
                failures = 0 if cnt > 0 else 1
            else:
                parser.error("小红书自动搜索需先通过 --login xhs 登录")
        elif args.command == "social":
            if args.watch:
                from src.social_downloader import watch_clipboard
                watch_clipboard(args.output_dir)
                return 0

            from src.social_downloader import download_url
            urls_to_download = []
            if args.url:
                urls_to_download.append(args.url)
            elif args.file:
                if not args.file.is_file():
                    parser.error(f"链接文件不存在：{args.file}")
                with open(args.file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            urls_to_download.append(line)
            else:
                parser.error("请提供链接、使用 --file 指定文本文件，或使用 --watch 启动剪贴板自动下载")

            failures = 0
            cookies_f = getattr(args, "cookies_file", None)
            for u in urls_to_download:
                ok = download_url(u, args.output_dir, cookies_file=cookies_f)
                if not ok:
                    failures += 1
    except (OSError, ValueError) as error:
        parser.exit(1, f"错误：{error}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
