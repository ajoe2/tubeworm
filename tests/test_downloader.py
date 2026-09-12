import copy
import json
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fixtures import MediaServer, make_video
from yt_dlp.utils import DownloadError

from app import downloader


class ExtractionCacheTests(unittest.TestCase):
    def test_concurrent_lookups_share_one_extraction_and_get_private_copies(self):
        downloader._cache.clear()
        calls = []

        def extract(*args, **kwargs):
            calls.append(1)
            time.sleep(0.05)
            return {"id": "test", "title": "Original"}

        with patch.object(downloader.YoutubeDL, "extract_info", side_effect=extract):
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(downloader._source_info, ["test"] * 4))
            results[0]["title"] = "Changed"
            self.assertEqual(downloader._source_info("test")["title"], "Original")
        self.assertEqual(len(calls), 1)


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        make_video(root / "video.mp4", audio=None)
        make_video(root / "audio.m4a", video=None)
        cls.server = MediaServer(root)
        base = cls.server.base
        source = {
            "id": "fixture",
            "title": "Fixture",
            "duration": 3,
            "extractor": "generic",
            "extractor_key": "Generic",
            "webpage_url": base,
            "formats": [
                {
                    "format_id": "audio",
                    "url": f"{base}/audio.m4a",
                    "ext": "m4a",
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                },
                {
                    "format_id": "video",
                    "url": f"{base}/video.mp4",
                    "ext": "mp4",
                    "vcodec": "avc1",
                    "acodec": "none",
                    "width": 160,
                    "height": 120,
                },
            ],
        }
        # Match real ingestion: extract_info returns a default format selection.
        with downloader.YoutubeDL({"quiet": True}) as ydl:
            cls.source = ydl.process_ie_result(source, download=False)

    @classmethod
    def tearDownClass(cls):
        cls.server.close()
        cls.temp.cleanup()

    def test_streams_download_in_parallel_and_mux_losslessly(self):
        for container in ("mkv", "mp4"):
            with self.subTest(container=container), tempfile.TemporaryDirectory() as tmp:
                events = []
                barrier = threading.Barrier(2)  # both streams must be in flight together
                original = downloader.YoutubeDL.process_ie_result

                def process(ydl, info, download=True, *, barrier=barrier, original=original, **kwargs):
                    if download:
                        barrier.wait(timeout=5)
                    return original(ydl, info, download=download, **kwargs)

                with (
                    patch.object(downloader, "_source_info", return_value=copy.deepcopy(self.source)),
                    patch.object(downloader.YoutubeDL, "process_ie_result", process),
                ):
                    result = downloader.download("fixture", "video+audio", container, tmp, events.append)

                self.assertEqual(result.title, "Fixture")
                self.assertEqual(result.ext, container)
                probe = json.loads(
                    subprocess.check_output(
                        [
                            "ffprobe",
                            "-v",
                            "error",
                            "-show_format",
                            "-show_streams",
                            "-of",
                            "json",
                            result.filepath,
                        ]
                    )
                )
                self.assertEqual({s["codec_name"] for s in probe["streams"]}, {"h264", "aac"})
                self.assertAlmostEqual(float(probe["format"]["duration"]), 3, delta=0.15)
                downloads = [e for e in events if e["phase"] == "download"]
                self.assertTrue(downloads)
                self.assertEqual({s["label"] for s in downloads[-1]["streams"]}, {"Video", "Audio"})
                self.assertTrue(
                    all(s["status"] == "finished" and s["percent"] == 100 for s in downloads[-1]["streams"])
                )
                self.assertEqual([e["step"] for e in events if e["phase"] == "process"], ["merge"])

    def test_rejected_stream_refreshes_the_link_and_retries(self):
        expired = copy.deepcopy(self.source)
        expired["formats"][0]["url"] = f"{self.server.base}/expired"
        downloader._cache["fixture"] = (time.monotonic(), expired)
        events = []
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                downloader, "_source_info", side_effect=[expired, copy.deepcopy(self.source)]
            ) as lookup,
        ):
            result = downloader.download("fixture", "audio", "m4a", tmp, events.append)
            self.assertTrue(Path(result.filepath).is_file())
        self.assertEqual(lookup.call_count, 2)
        self.assertNotIn("fixture", downloader._cache)
        self.assertIn({"phase": "process", "step": "retry"}, events)

    def test_retry_is_bounded_and_only_for_403(self):
        for message, attempts in [("HTTP Error 403: Forbidden", 2), ("HTTP Error 404: Not Found", 1)]:
            with (
                self.subTest(message=message),
                tempfile.TemporaryDirectory() as tmp,
                patch.object(downloader, "_download", side_effect=DownloadError(message)) as attempt,
            ):
                with self.assertRaises(DownloadError):
                    downloader.download("fixture", "best", "mkv", tmp, lambda e: None)
                self.assertEqual(attempt.call_count, attempts)


if __name__ == "__main__":
    unittest.main()
