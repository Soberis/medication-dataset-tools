"""Authorized video download and hand-presence screening."""

import argparse
import csv
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
MANIFEST = ROOT / "metadata" / "manifest.json"


def load_urls(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"source_url", "license_note"} <= set(reader.fieldnames or []):
            raise ValueError("CSV must contain source_url and license_note")
        rows = []
        for number, row in enumerate(reader, 2):
            url = (row.get("source_url") or "").strip()
            note = (row.get("license_note") or "").strip()
            if not url and not note:
                continue
            if not url.startswith("https://www.bilibili.com/video/") or not note:
                raise ValueError(f"line {number}: Bilibili video URL and license_note required")
            rows.append((url, note))
        return rows


def read_manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"schema_version": 1, "items": []}


def save_manifest(data):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    temporary = MANIFEST.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(MANIFEST)


def download(rows):
    manifest = read_manifest()
    by_url = {item["source_url"]: item for item in manifest["items"]}
    for url, note in rows:
        if url in by_url and by_url[url].get("status") not in {"DOWNLOAD_FAILED"}:
            continue
        command = [
            "yt-dlp", "--no-playlist", "--no-overwrites", "--write-info-json",
            "--merge-output-format", "mp4", "-f",
            "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "-o", str(RAW / "%(id)s" / "%(id)s.%(ext)s"), url,
        ]
        result = subprocess.run(command, check=False)
        item = by_url.get(url, {"source": "bilibili", "source_url": url})
        item["license_note"] = note
        item["status"] = "DOWNLOADED" if result.returncode == 0 else "DOWNLOAD_FAILED"
        item["updated_at"] = datetime.now(timezone.utc).isoformat()
        if result.returncode == 0:
            match = re.search(r"/video/(BV[0-9A-Za-z]+)", url)
            infos = list((RAW / match.group(1)).glob("*.info.json")) if match else []
            if infos:
                info_path = infos[0]
                info = json.loads(info_path.read_text(encoding="utf-8"))
                item.update({
                    "video_id": info.get("id"), "title": info.get("title"),
                    "uploader": info.get("uploader"), "duration_sec": info.get("duration"),
                    "upload_date": info.get("upload_date"), "description": info.get("description"),
                    "info_json": str(info_path.relative_to(ROOT)),
                })
                videos = [p for p in info_path.parent.iterdir() if p.suffix.lower() in {".mp4", ".mkv", ".webm"}]
                if videos:
                    item["video_path"] = str(videos[0].relative_to(ROOT))
        by_url[url] = item
        manifest["items"] = list(by_url.values())
        save_manifest(manifest)


def screen(sample_fps, accept, review):
    import cv2
    import mediapipe as mp

    if not hasattr(mp, "solutions"):
        raise RuntimeError("Installed MediaPipe lacks solutions.hands; use a compatible MediaPipe release")
    manifest = read_manifest()
    with mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=2) as detector:
        for item in manifest["items"]:
            path = ROOT / item.get("video_path", "")
            if not item.get("video_path") or not path.is_file():
                continue
            capture = cv2.VideoCapture(str(path))
            try:
                fps = capture.get(cv2.CAP_PROP_FPS)
                frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
                if fps <= 0 or frames <= 0:
                    item["status"] = "SCREEN_FAILED"
                    item["screen_error"] = "Video duration unavailable"
                    continue
                step = max(1, round(fps / sample_fps))
                sampled = detected = 0
                for index in range(0, frames, step):
                    capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                    ok, frame = capture.read()
                    if not ok:
                        continue
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    sampled += 1
                    detected += bool(detector.process(rgb).multi_hand_landmarks)
                if not sampled:
                    item["status"] = "SCREEN_FAILED"
                    item["screen_error"] = "No decodable frames"
                    continue
                ratio = detected / sampled
                item.update({"sampled_frames": sampled, "hand_frames": detected,
                             "hand_ratio": round(ratio, 4), "sample_fps": sample_fps,
                             "status": "ACCEPTED" if ratio >= accept else "REVIEW" if ratio >= review else "REJECTED"})
                item.pop("screen_error", None)
            finally:
                capture.release()
                save_manifest(manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("download")
    fetch.add_argument("--urls", type=Path, default=ROOT / "urls.csv")
    filter_command = commands.add_parser("screen")
    filter_command.add_argument("--sample-fps", type=float, default=2.0)
    filter_command.add_argument("--accept", type=float, default=0.60)
    filter_command.add_argument("--review", type=float, default=0.20)
    args = parser.parse_args()
    if args.command == "download":
        download(load_urls(args.urls))
    else:
        if args.sample_fps <= 0 or not 0 <= args.review < args.accept <= 1:
            parser.error("require sample-fps > 0 and 0 <= review < accept <= 1")
        screen(args.sample_fps, args.accept, args.review)


if __name__ == "__main__":
    main()
