import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fixtures import make_video

from app import downloader, media
from app.jobs import JobManager, clip_title
from app.models import ExportRequest, JobStatus, MediaInfo


class JobTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.original = str(make_video(root / "original.mkv", audio="libopus"))
        cls.proxy = str(make_video(root / "proxy.mp4"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    async def asyncSetUp(self):
        self.manager = JobManager()

    async def asyncTearDown(self):
        self.manager.shutdown()

    def patches(self, **overrides):
        """Stub the network: the "download" hands back the locally generated original."""
        defaults = {
            "fetch_info": dict(return_value=MediaInfo(title="Fixture", duration=3)),
            "download": dict(return_value=downloader.Downloaded(self.original, "Fixture", "mkv")),
            "download_proxy": dict(return_value=self.proxy),
        }
        defaults.update(overrides)
        return [patch.object(downloader, name, **spec) for name, spec in defaults.items()]

    async def prepare(self, **overrides):
        patches = self.patches(**overrides)
        for p in patches:
            p.start()
        try:
            job = self.manager.create_preview("fixture")
            await asyncio.wait_for(job.done.wait(), 10)
        finally:
            for p in patches:
                p.stop()
        return job

    async def collect(self, job):
        events = []
        while (event := await job.queue.get()) is not None:
            events.append(event)
        return events

    async def test_preview_job_reports_both_downloads_and_ends_ready(self):
        job = await self.prepare()
        self.assertEqual(job.status, JobStatus.completed, job.error)
        self.assertEqual(job.filepath, self.original)
        self.assertTrue(Path(job.previewpath).is_file())
        self.assertAlmostEqual(job.duration, 3, delta=0.1)
        events = await self.collect(job)
        self.assertEqual(events[-2], {"phase": "proxy", "status": "ready"})
        self.assertEqual(events[-1]["status"], "completed")
        self.assertEqual(events[-1]["lossless"], ["opus", "mkv"])

    async def test_proxy_downloads_concurrently_with_the_original(self):
        barrier = threading.Barrier(2)

        def original(*args, **kwargs):
            barrier.wait(timeout=3)
            return downloader.Downloaded(self.original, "Fixture", "mkv")

        def proxy(*args, **kwargs):
            barrier.wait(timeout=3)
            return self.proxy

        job = await self.prepare(download=dict(side_effect=original), download_proxy=dict(side_effect=proxy))
        self.assertEqual(job.status, JobStatus.completed, job.error)

    async def test_proxy_failure_falls_back_to_the_original(self):
        job = await self.prepare(download_proxy=dict(side_effect=RuntimeError("no proxy format")))
        self.assertEqual(job.status, JobStatus.completed, job.error)
        self.assertTrue(Path(job.previewpath).is_file())
        self.assertEqual(media.probe(job.previewpath).video, "h264")

    async def test_source_failure_is_reported(self):
        job = await self.prepare(download=dict(side_effect=RuntimeError("ERROR: Video unavailable")))
        self.assertEqual(job.status, JobStatus.error)
        self.assertEqual(job.error, "Video unavailable")
        self.assertEqual(
            (await self.collect(job))[-1],
            {"phase": "complete", "status": "error", "error": "Video unavailable"},
        )

    async def test_live_streams_are_rejected(self):
        job = await self.prepare(fetch_info=dict(return_value=MediaInfo(title="Live", duration=None)))
        self.assertEqual(job.status, JobStatus.error)
        self.assertIn("finished videos", job.error)

    async def test_repeated_exports_reuse_the_source(self):
        source = await self.prepare()
        with patch.object(downloader, "download", side_effect=AssertionError("must not download again")):
            for media_type in ("video", "audio"):
                req = ExportRequest(media_type=media_type, start_time=0.4, end_time=1.6)
                job = self.manager.create_export(source, req)
                self.assertEqual(source.users, 1)
                await asyncio.wait_for(job.done.wait(), 20)
                self.assertEqual(job.status, JobStatus.completed, job.error)
                self.assertEqual(source.users, 0)
                self.assertEqual(job.title, "Fixture [0m00s-0m01s]")
                self.assertAlmostEqual(media.probe(job.filepath).duration, 1.2, delta=0.1)
        self.assertTrue(Path(source.filepath).exists())

    async def test_sources_in_use_survive_the_sweep(self):
        source = await self.prepare()
        source.finished_at = time.monotonic() - 7200
        source.users = 1
        self.manager.sweep()
        self.assertIs(self.manager.get(source.id), source)
        source.users = 0
        self.manager.sweep()
        self.assertIsNone(self.manager.get(source.id))
        self.assertFalse(Path(source.tmpdir).exists())

    def test_clip_title(self):
        self.assertEqual(clip_title("T", ExportRequest(), 90), "T")
        self.assertEqual(clip_title("T", ExportRequest(start_time=0.02, end_time=89.99), 90), "T")
        self.assertEqual(
            clip_title("T", ExportRequest(start_time=5, end_time=3725), 4000), "T [0m05s-1h02m05s]"
        )


class RouteTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.original = str(make_video(Path(cls.temp.name) / "original.mkv"))
        cls.probe = media.probe(cls.original)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    async def asyncSetUp(self):
        from app import main

        self.main = main
        self.manager = JobManager()
        self.patch = patch.object(main, "manager", self.manager)
        self.patch.start()
        job = self.manager._start("fixture", lambda job, emit: asyncio.sleep(0))
        job.filepath, job.ext, job.previewpath = self.original, "mkv", self.original
        job.probe = self.probe
        await asyncio.wait_for(job.done.wait(), 5)
        self.job = job

    async def asyncTearDown(self):
        self.manager.shutdown()
        self.patch.stop()

    async def test_preview_media_supports_ranges_inline(self):
        response = await self.main.preview_media(self.job.id)
        messages = []

        async def send(message):
            messages.append(message)

        async def receive():
            return {"type": "http.request"}

        await response(
            {"type": "http", "method": "GET", "headers": [(b"range", b"bytes=0-99")]}, receive, send
        )
        self.assertEqual(messages[0]["status"], 206)
        self.assertEqual(sum(len(m.get("body", b"")) for m in messages), 100)
        self.assertNotIn(b"attachment", dict(messages[0]["headers"]).get(b"content-disposition", b""))

    async def test_exports_are_validated(self):
        for interval in ({"start_time": 5}, {"end_time": 4}):
            with self.assertRaises(HTTPException) as error:
                await self.main.create_export(self.job.id, ExportRequest(**interval))
            self.assertEqual(error.exception.status_code, 422)
        with self.assertRaises(HTTPException) as error:
            await self.main.create_export("missing", ExportRequest())
        self.assertEqual(error.exception.status_code, 404)

    async def test_file_download_name(self):
        self.job.title = 'A/B: "c"?'
        self.assertEqual(self.main._download_name(self.job), "A_B_ _c__.mkv")


if __name__ == "__main__":
    unittest.main()
