import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixtures import make_video
from pydantic import ValidationError

from app import media
from app.models import ExportRequest


def codecs(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", path])
    return {s["codec_type"]: s["codec_name"] for s in json.loads(out)["streams"]}


def duration(path):
    return float(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path]
        )
    )


class ExportRequestTests(unittest.TestCase):
    def test_invalid_intervals_are_rejected(self):
        for interval in (
            {"start_time": -1},
            {"start_time": 2, "end_time": 2},
            {"end_time": float("inf")},
            {"start_time": float("nan")},
        ):
            with self.assertRaises(ValidationError):
                ExportRequest(**interval)


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.h264_aac = str(make_video(root / "h264_aac.mkv"))
        cls.h264_opus = str(make_video(root / "h264_opus.mkv", audio="libopus"))
        cls.vp9_opus = str(make_video(root / "vp9_opus.mkv", audio="libopus", video="libvpx-vp9"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_probe_and_lossless_containers(self):
        self.assertEqual(media.lossless_containers(media.probe(self.h264_aac)), ["m4a", "mkv", "mp4"])
        self.assertEqual(media.lossless_containers(media.probe(self.h264_opus)), ["opus", "mkv"])
        self.assertEqual(media.lossless_containers(media.probe(self.vp9_opus)), ["opus", "mkv"])

    def test_whole_export_copies_streams_when_the_container_allows(self):
        cases = [  # (source, media_type, mode, expected codecs, step)
            (self.vp9_opus, "video", "quality", {"video": "vp9", "audio": "opus"}, "remux"),
            (self.vp9_opus, "video", "compatibility", {"video": "h264", "audio": "aac"}, "convert"),
            (self.h264_opus, "video", "compatibility", {"video": "h264", "audio": "aac"}, "convert"),
            (self.h264_aac, "video", "compatibility", {"video": "h264", "audio": "aac"}, "remux"),
            (self.vp9_opus, "audio", "quality", {"audio": "opus"}, "remux"),
            (self.vp9_opus, "audio", "compatibility", {"audio": "aac"}, "convert"),
        ]
        for source, media_type, mode, expected, step in cases:
            with (
                self.subTest(source=Path(source).name, media_type=media_type, mode=mode),
                tempfile.TemporaryDirectory() as tmp,
            ):
                events = []
                req = ExportRequest(media_type=media_type, mode=mode)
                out = media.export_clip(source, media.probe(source), req, tmp, events.append)
                self.assertEqual(codecs(out), expected)
                self.assertAlmostEqual(duration(out), 3, delta=0.15)
                self.assertEqual(events, [{"phase": "process", "step": step}])

    def test_trimmed_export_is_precise_for_every_format(self):
        for media_type in ("audio", "video"):
            for mode in ("quality", "compatibility"):
                with self.subTest(media_type=media_type, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    events = []
                    req = ExportRequest(media_type=media_type, mode=mode, start_time=0.4, end_time=1.6)
                    out = media.export_clip(
                        self.vp9_opus, media.probe(self.vp9_opus), req, tmp, events.append
                    )
                    self.assertAlmostEqual(duration(out), 1.2, delta=0.1)
                    self.assertEqual(
                        set(codecs(out)), {"audio", "video"} if media_type == "video" else {"audio"}
                    )
                    self.assertEqual(events, [{"phase": "process", "step": "trim"}])

    def test_audio_export_needs_an_audio_track(self):
        silent = str(make_video(Path(self.temp.name) / "silent.mp4", audio=None))
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, "no audio"):
            media.export_clip(
                silent, media.probe(silent), ExportRequest(media_type="audio"), tmp, lambda e: None
            )

    def test_preview_reuses_or_remuxes_compatible_media(self):
        mp4 = str(Path(self.temp.name) / "compatible.mp4")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                self.h264_aac,
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                mp4,
            ],
            check=True,
        )
        with patch.object(media, "run_ffmpeg", side_effect=AssertionError("compatible MP4 must be reused")):
            self.assertEqual(media.prepare_preview(mp4, self.temp.name, lambda e: None), mp4)

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(media, "run_ffmpeg", wraps=media.run_ffmpeg) as ffmpeg,
        ):
            out = media.prepare_preview(self.h264_aac, tmp, lambda e: None)  # mkv: remux only
            args = ffmpeg.call_args.args[0]
            self.assertEqual(args[args.index("-c:v") + 1], "copy")
            self.assertEqual(args[args.index("-c:a") + 1], "copy")
            self.assertEqual(codecs(out), {"video": "h264", "audio": "aac"})

        with tempfile.TemporaryDirectory() as tmp:
            out = media.prepare_preview(self.vp9_opus, tmp, lambda e: None)  # must transcode
            self.assertEqual(codecs(out), {"video": "h264", "audio": "aac"})


if __name__ == "__main__":
    unittest.main()
