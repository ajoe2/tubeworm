import copy
import functools
import json
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError
from yt_dlp.utils import DownloadError
from app import downloader
from app.models import JobRequest


class IntervalTests(unittest.TestCase):
    def test_invalid_intervals(self):
        for interval in ({'start_time': -1}, {'start_time': 2, 'end_time': 2},
                         {'end_time': float('inf')}, {'start_time': float('nan')}):
            with self.assertRaises(ValidationError):
                JobRequest(url='test', media_type='video', mode='quality', **interval)

    def test_extraction_shared_and_isolated(self):
        downloader._cache.clear()
        calls = []
        def extract(*args, **kwargs):
            calls.append(1)
            time.sleep(.05)
            return {'id': 'test', 'title': 'Original'}
        with patch.object(downloader.YoutubeDL, 'extract_info', side_effect=extract):
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(downloader._source_info, ['test'] * 4))
            results[0]['title'] = 'Changed'
            self.assertEqual(downloader._source_info('test')['title'], 'Original')
        self.assertEqual(len(calls), 1)


class QuietHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/expired':
            self.send_error(403)
            return
        super().do_GET()

    def log_message(self, *args):
        pass


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=size=160x120:rate=30:duration=3', '-c:v', 'libx264',
                        str(root / 'video.mp4')], check=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=3', '-c:a', 'aac',
                        str(root / 'audio.m4a')], check=True)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(root)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.source = {'id': 'fixture', 'title': 'Fixture', 'duration': 3,
                      'extractor': 'generic', 'extractor_key': 'Generic',
                      'webpage_url': base, 'formats': [
                          {'format_id': 'audio', 'url': base + '/audio.m4a', 'ext': 'm4a', 'vcodec': 'none', 'acodec': 'mp4a.40.2'},
                          {'format_id': 'video', 'url': base + '/video.mp4', 'ext': 'mp4', 'vcodec': 'avc1', 'acodec': 'none', 'width': 160, 'height': 120},
                      ]}

        # Match real ingestion: extract_info returns a default format selection.
        with downloader.YoutubeDL({"quiet": True}) as ydl:
            cls.source = ydl.process_ie_result(cls.source, download=False)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def test_outputs_and_precise_duration(self):
        for media_type in ('audio', 'video'):
            for mode in ('quality', 'compatibility'):
                for crop in (False, True):
                    with self.subTest(media_type=media_type, mode=mode, crop=crop), tempfile.TemporaryDirectory() as tmp:
                        req = JobRequest(url='fixture', media_type=media_type, mode=mode,
                                         start_time=.4 if crop else 0, end_time=1.6 if crop else None)
                        events = []
                        # Both video streams must reach process_ie_result concurrently.
                        barrier = threading.Barrier(2)
                        original = downloader.YoutubeDL.process_ie_result
                        def process(ydl, info, download=True, **kwargs):
                            if download and media_type == 'video':
                                barrier.wait(timeout=5)
                            return original(ydl, info, download=download, **kwargs)
                        with patch.object(downloader, '_source_info', return_value=self.source), patch.object(downloader.YoutubeDL, 'process_ie_result', process):
                            result = downloader.run_download(req, tmp, events.append)
                        probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', result['filepath']]))
                        self.assertAlmostEqual(float(probe['format']['duration']), 1.2 if crop else 3, delta=.15)
                        types = {s['codec_type'] for s in probe['streams']}
                        self.assertEqual(types, {'audio', 'video'} if media_type == 'video' else {'audio'})
                        downloads = [e for e in events if e['phase'] == 'download']
                        self.assertTrue(downloads)
                        streams = downloads[-1]['streams']
                        self.assertEqual({s['label'] for s in streams}, {'Video', 'Audio'} if media_type == 'video' else {'Audio'})
                        self.assertTrue(all(s['status'] == 'finished' and s['percent'] == 100 for s in streams))

    def test_out_of_bounds_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(downloader, '_source_info', return_value=self.source):
            with self.assertRaisesRegex(ValueError, 'outside'):
                downloader.run_download(JobRequest(url='fixture', media_type='video', mode='quality', end_time=4), tmp, lambda e: None)

    def test_rejected_stream_refreshes_and_downloads(self):
        expired = copy.deepcopy(self.source)
        expired['formats'][0]['url'] = f'http://127.0.0.1:{self.server.server_port}/expired'
        req = JobRequest(url='fixture', media_type='audio', mode='compatibility')
        downloader._cache['fixture'] = (time.monotonic(), expired)
        events = []
        with tempfile.TemporaryDirectory() as tmp, patch.object(downloader, '_source_info', side_effect=[expired, self.source]) as lookup:
            result = downloader.run_download(req, tmp, events.append)
            self.assertTrue(Path(result['filepath']).is_file())
            self.assertEqual(lookup.call_count, 2)
            self.assertNotIn('fixture', downloader._cache)
            self.assertTrue(any(e.get('postprocessor') == 'Refresh' for e in events))

    def test_retry_is_bounded_and_only_for_403(self):
        req = JobRequest(url='fixture', media_type='video', mode='quality')
        for message, count in [('HTTP Error 403: Forbidden', 2), ('HTTP Error 404: Not Found', 1)]:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                with patch.object(downloader, '_run_download', side_effect=DownloadError(message)) as attempt:
                    with self.assertRaises(DownloadError):
                        downloader.run_download(req, tmp, lambda e: None)
                    self.assertEqual(attempt.call_count, count)


if __name__ == '__main__':
    unittest.main()
