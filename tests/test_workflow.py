import json
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src.downloader import download
from src.manifest import append_candidates, read_candidates
from src.search import candidate, search


BV1 = "BV1234567890"
BV2 = "BVabcdefghij"


def row(bvid, selected="0"):
    return {"selected": selected, "bvid": bvid, "title": "配药", "url": f"https://www.bilibili.com/video/{bvid}",
            "keyword": "配药", "uploader": "", "duration": ""}


class WorkflowTests(unittest.TestCase):
    def test_search_appends_and_preserves_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords = root / "keywords.txt"
            keywords.write_text("护士 配药\n", encoding="utf-8")
            csv_path = root / "candidates.csv"
            append_candidates(csv_path, [row(BV1, "1")])
            entries = {"entries": [{"id": BV1, "title": "已有"}, {"id": BV2, "title": "第一视角手部配药", "uploader": "护士", "duration": 90, "thumbnail": "https://example.com/cover.jpg"},
                                   {"id": "BVzzzzzzzzzz", "title": "配药考试"}]}
            with patch("src.search.subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(entries), "")) as run, redirect_stdout(io.StringIO()):
                added, failures = search(keywords, csv_path, 50)
            self.assertEqual((added, failures), (1, 0))
            self.assertIn("bilisearch50:护士 配药", run.call_args.args[0])
            self.assertEqual([(item["bvid"], item["selected"]) for item in read_candidates(csv_path)], [(BV1, "1"), (BV2, "0")])
            self.assertEqual(read_candidates(csv_path)[1]["title_hint"], "优先预览")
            self.assertEqual(read_candidates(csv_path)[1]["thumbnail"], "https://example.com/cover.jpg")

    def test_download_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "candidates.csv"
            append_candidates(csv_path, [row(BV1, "1"), row(BV2, "1")])
            with patch("src.downloader.subprocess.run", side_effect=[subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0)]) as run, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(download(csv_path, root), (1, 1))
            self.assertEqual(run.call_count, 2)
            self.assertIn("--download-archive", run.call_args.args[0])
            self.assertIn("--remux-video", run.call_args.args[0])
            self.assertIn(str(root / BV2 / f"{BV2}.%(ext)s"), run.call_args.args[0])
            self.assertIn("下载失败", (root / "download.log").read_text(encoding="utf-8"))

    def test_candidate_requires_bvid_and_relevant_title(self):
        self.assertIsNone(candidate({"id": "123", "title": "配药"}, "配药"))
        self.assertIsNone(candidate({"id": BV1, "title": "PPT 配药"}, "配药"))
        self.assertIsNone(candidate({"id": BV1, "title": "护士工作第一视角"}, "配药"))

    def test_search_retries_412_and_keeps_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords = root / "keywords.txt"
            keywords.write_text("护士 配药\n", encoding="utf-8")
            csv_path = root / "candidates.csv"
            blocked = subprocess.CompletedProcess([], 0, json.dumps({"entries": [None]}), "ERROR: HTTP Error 412: Precondition Failed")
            recovered = subprocess.CompletedProcess([], 0, json.dumps({"entries": [{"id": BV1, "title": "护士第一视角配药"}]}), "")
            with patch("src.search.subprocess.run", side_effect=[blocked, recovered]) as run, \
                 patch("src.search.time.sleep") as sleep, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(search(keywords, csv_path, 50), (1, 0))
            self.assertEqual(run.call_count, 2)
            sleep.assert_called_once_with(3)
            self.assertEqual(read_candidates(csv_path)[0]["bvid"], BV1)

    def test_search_stops_after_two_persistent_412_keywords(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords = root / "keywords.txt"
            keywords.write_text("第一视角 配药\n护士 配药\n安瓿 抽药\n", encoding="utf-8")
            blocked = subprocess.CompletedProcess([], 0, json.dumps({"entries": [None]}), "ERROR: HTTP Error 412")
            with patch("src.search.subprocess.run", return_value=blocked) as run, \
                 patch("src.search.time.sleep"), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(search(keywords, root / "candidates.csv", 1), (0, 2))
            self.assertEqual(run.call_count, 6)

    def test_main_cli_download_default_output_dir(self):
        import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            candidates = root / "data" / "candidates.csv"
            candidates.write_text("selected,bvid,title,url,keyword,uploader,duration\n", encoding="utf-8-sig")
            with patch.object(main, "ROOT", root), \
                 patch("sys.argv", ["main.py", "download"]), \
                 patch("main.download", return_value=(0, 0)) as mock_download:
                exit_code = main.main()
                self.assertEqual(exit_code, 0)
                mock_download.assert_called_once_with(candidates, main.DEFAULT_DOWNLOAD_DIR, None, None)

    def test_browser_cookies_are_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords = root / "keywords.txt"
            keywords.write_text("护士 配药\n", encoding="utf-8")
            response = subprocess.CompletedProcess([], 0, json.dumps({"entries": []}), "")
            with patch("src.search.subprocess.run", return_value=response) as run, redirect_stdout(io.StringIO()):
                search(keywords, root / "candidates.csv", 1, "edge")
            self.assertIn("--cookies-from-browser", run.call_args.args[0])
            self.assertIn("edge", run.call_args.args[0])

    def test_cookie_file_is_passed_to_ytdlp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords = root / "keywords.txt"
            keywords.write_text("护士 配药\n", encoding="utf-8")
            cookies = root / "cookies.txt"
            cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            response = subprocess.CompletedProcess([], 0, json.dumps({"entries": []}), "")
            with patch("src.search.subprocess.run", return_value=response) as run, redirect_stdout(io.StringIO()):
                search(keywords, root / "candidates.csv", 1, cookies_file=cookies)
            self.assertIn("--cookies", run.call_args.args[0])
            self.assertIn(str(cookies), run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
