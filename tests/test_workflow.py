import json
import subprocess
import tempfile
import unittest
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
            entries = {"entries": [{"id": BV1, "title": "已有"}, {"id": BV2, "title": "手部配药", "uploader": "护士", "duration": 90},
                                   {"id": "BVzzzzzzzzzz", "title": "配药考试"}]}
            with patch("src.search.subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(entries), "")) as run:
                added, failures = search(keywords, csv_path, 50)
            self.assertEqual((added, failures), (1, 0))
            self.assertIn("bilisearch50:护士 配药", run.call_args.args[0])
            self.assertEqual([(item["bvid"], item["selected"]) for item in read_candidates(csv_path)], [(BV1, "1"), (BV2, "0")])

    def test_download_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "candidates.csv"
            append_candidates(csv_path, [row(BV1, "1"), row(BV2, "1")])
            with patch("src.downloader.subprocess.run", side_effect=[subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0)]) as run:
                self.assertEqual(download(csv_path, root), (1, 1))
            self.assertEqual(run.call_count, 2)
            self.assertIn("--download-archive", run.call_args.args[0])
            self.assertIn("--remux-video", run.call_args.args[0])
            self.assertIn("下载失败", (root / "download.log").read_text(encoding="utf-8"))

    def test_candidate_requires_bvid_and_relevant_title(self):
        self.assertIsNone(candidate({"id": "123", "title": "配药"}, "配药"))
        self.assertIsNone(candidate({"id": BV1, "title": "PPT 配药"}, "配药"))


if __name__ == "__main__":
    unittest.main()
