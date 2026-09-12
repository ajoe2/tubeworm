import asyncio
import json
import subprocess
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from app import downloader
from app.jobs import Job, JobManager
from app.models import JobRequest, JobStatus, MediaInfo
from app.main import ExportRequest, create_export, preview_media


class EditorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = str(Path(self.temp.name) / 'original.mkv')
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=size=160x120:rate=30:duration=3', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=3', '-c:v', 'libx264', '-c:a', 'aac',
                        self.original], check=True)
        self.manager = JobManager()
        self.manager_patch = patch('app.main.manager', self.manager)
        self.manager_patch.start()
        self.req = JobRequest(url='fixture', media_type='video', mode='quality')

    async def asyncTearDown(self):
        self.manager.shutdown()
        self.manager_patch.stop()
        self.temp.cleanup()

    async def prepare(self):
        with patch.object(downloader, 'fetch_info', return_value=MediaInfo(duration=3)), patch.object(downloader, 'run_download', return_value={'filepath':self.original,'title':'Fixture','ext':'mkv'}):
            job = self.manager.create(self.req, preview=True)
            await asyncio.wait_for(job.done.wait(), 10)
        self.assertEqual(job.status, JobStatus.completed, job.error)
        self.assertAlmostEqual(job.duration, 3, delta=.1)
        return job

    async def test_preview_playback_ranges_and_repeated_exports(self):
        source = await self.prepare()
        probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',source.previewpath]))
        self.assertEqual({s['codec_name'] for s in probe['streams']}, {'h264','aac'})
        response = await preview_media(source.id)
        messages = []
        async def send(message): messages.append(message)
        async def receive(): return {'type':'http.request'}
        await response({'type':'http','method':'GET','headers':[(b'range',b'bytes=0-99')]}, receive, send)
        self.assertEqual(messages[0]['status'], 206)
        self.assertEqual(sum(len(m.get('body',b'')) for m in messages), 100)
        self.assertNotIn(b'attachment', dict(messages[0]['headers']).get(b'content-disposition',b''))
        with patch.object(downloader, 'run_download', side_effect=AssertionError('Export must not download again')):
            for media_type in ('video','audio'):
                created = await create_export(source.id, ExportRequest(start_time=.4,end_time=1.6,media_type=media_type))
                job = self.manager.get(created.id)
                self.assertEqual(source.users,1)
                await asyncio.wait_for(job.done.wait(), 10)
                self.assertEqual(job.status, JobStatus.completed, job.error)
                duration = float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',job.filepath]))
                self.assertAlmostEqual(duration,1.2,delta=.1)
                self.assertEqual(source.users,0)
        self.assertTrue(Path(source.previewpath).exists())

    async def test_rejects_invalid_and_expired_exports(self):
        source = await self.prepare()
        for interval in ({'start_time':2,'end_time':1},{'end_time':4},{'start_time':-1},{'end_time':float('nan')}):
            with self.assertRaises(HTTPException) as error:
                await create_export(source.id, ExportRequest(**interval))
            self.assertEqual(error.exception.status_code,422)
        with self.assertRaises(HTTPException) as error:
            await create_export('missing', ExportRequest())
        self.assertEqual(error.exception.status_code,404)

    async def test_active_source_survives_cleanup(self):
        source = await self.prepare()
        source.finished_at = time.monotonic()-7200
        source.users = 1
        self.manager._sweep_finished()
        self.assertIs(self.manager.get(source.id), source)
        source.users = 0
        self.manager._sweep_finished()
        self.assertIsNone(self.manager.get(source.id))


    async def test_preview_download_overlaps_original(self):
        barrier = threading.Barrier(2)
        proxy = str(Path(self.temp.name) / "proxy.mp4")
        subprocess.run(['ffmpeg','-v','error','-i',self.original,'-c','copy','-movflags','+faststart',proxy],check=True)
        def original(*args, **kwargs):
            barrier.wait(timeout=3)
            return {'filepath':self.original,'title':'Fixture','ext':'mkv'}
        def preview(*args, **kwargs):
            barrier.wait(timeout=3)
            return proxy, 3.0
        with patch.object(downloader,'fetch_info',return_value=MediaInfo(duration=3)), patch.object(downloader,'run_download',side_effect=original), patch.object(downloader,'download_preview',side_effect=preview):
            job = self.manager.create(self.req,preview=True)
            await asyncio.wait_for(job.done.wait(),5)
        self.assertEqual(job.status,JobStatus.completed,job.error)
        self.assertEqual(job.filepath,self.original)
        self.assertEqual(job.previewpath,proxy)

    async def test_compatible_preview_is_not_reencoded(self):
        mp4 = str(Path(self.temp.name) / 'source.mp4')
        subprocess.run(['ffmpeg','-v','error','-i',self.original,'-c','copy','-movflags','+faststart',mp4],check=True)
        with patch.object(downloader,'_ffmpeg',side_effect=AssertionError('MP4 should be reused')):
            path,duration = downloader.prepare_preview(mp4,self.temp.name,lambda e:None)
        self.assertEqual(path,mp4)
        self.assertAlmostEqual(duration,3,delta=.1)
        with patch.object(downloader,'_ffmpeg',wraps=downloader._ffmpeg) as ffmpeg:
            downloader.prepare_preview(self.original,self.temp.name,lambda e:None)
        args = ffmpeg.call_args.args[0]
        self.assertEqual(args[args.index('-c:v')+1],'copy')
        self.assertEqual(args[args.index('-c:a')+1],'copy')

    async def test_proxy_failure_falls_back_to_original(self):
        with patch.object(downloader,'fetch_info',return_value=MediaInfo(duration=3)), patch.object(downloader,'run_download',return_value={'filepath':self.original,'title':'Fixture','ext':'mkv'}), patch.object(downloader,'download_preview',side_effect=RuntimeError('No preview format')):
            job=self.manager.create(self.req,preview=True)
            await asyncio.wait_for(job.done.wait(),5)
        self.assertEqual(job.status,JobStatus.completed,job.error)
        self.assertTrue(Path(job.previewpath).exists())
