"""Launcher regression checks: stale PIDs and Windows batch encoding."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('start_local', ROOT / 'scripts/start_local.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class StartupTests(unittest.TestCase):
    def test_missing_identity_never_marks_reused_pid_alive(self):
        with patch.object(launcher, 'process_identity') as identity:
            self.assertFalse(launcher.same_process({'pid': 123}))
            identity.assert_not_called()

    def test_creation_time_must_match(self):
        record = {'pid': 123, 'identity': {'image': 'python.exe', 'created': 1}}
        with patch.object(launcher, 'process_identity', return_value={'image': 'python.exe', 'created': 2}):
            self.assertFalse(launcher.same_process(record))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows process query')
    def test_liveness_check_does_not_terminate_process(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            record = {'pid': child.pid, 'identity': launcher.process_identity(child.pid)}
            self.assertTrue(record['identity'])
            self.assertTrue(launcher.same_process(record))
            self.assertIsNone(child.poll())
        finally:
            child.terminate()
            child.wait(timeout=5)
        self.assertFalse(launcher.same_process(record))

    def test_batch_files_are_ascii_crlf(self):
        for path in [ROOT / '启动工作台.cmd', ROOT / 'Start-Workbench.cmd', ROOT.parent / '打开选品工作台.cmd']:
            raw = path.read_bytes()
            self.assertTrue(raw.isascii(), str(path))
            self.assertIn(b'\r\n', raw)
            self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))

    def test_health_check_rejects_other_service(self):
        with patch.object(launcher, 'request', return_value={'status': 'ok'}):
            self.assertFalse(launcher.healthy(8010))

    def test_failed_child_is_reported_without_waiting_full_timeout(self):
        child = Mock()
        child.poll.return_value = 1
        with self.assertRaisesRegex(RuntimeError, 'web'):
            launcher.wait_until(lambda: False, 'web', child, timeout=60)


if __name__ == '__main__':
    unittest.main()
