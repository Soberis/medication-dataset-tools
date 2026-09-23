"""Bilibili medication video search and download CLI."""

import argparse
from pathlib import Path

from src.downloader import download
from src.search import search


ROOT = Path(__file__).resolve().parent


DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads"


def main() -> int:
    parser = argparse.ArgumentParser(description="B 站配药视频候选搜索与人工选定下载")
    commands = parser.add_subparsers(dest="command", required=True)
    search_command = commands.add_parser("search", help="搜索并追加候选")
    search_command.add_argument("--limit", type=int, default=50, help="每个关键词搜索结果数，默认 50")
    download_command = commands.add_parser("download", help="下载 CSV 中 selected=1 的视频")
    download_command.add_argument("--output-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR,
                                  help=f"下载保存目录，默认系统下载目录 ({DEFAULT_DOWNLOAD_DIR})")
    args = parser.parse_args()
    data_dir = ROOT / "data"
    try:
        if args.command == "search":
            if args.limit < 1:
                parser.error("--limit 必须大于 0")
            _, failures = search(ROOT / "config" / "keywords.txt", data_dir / "candidates.csv", args.limit)
        else:
            if not (data_dir / "candidates.csv").exists():
                parser.error("请先执行 search，或创建 data/candidates.csv")
            _, failures = download(data_dir / "candidates.csv", args.output_dir)
    except (OSError, ValueError) as error:
        parser.exit(1, f"错误：{error}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
