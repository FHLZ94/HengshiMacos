import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]


class PackagedBackendStartupTests(unittest.TestCase):
    def test_backend_health_and_state_bridge_start_before_gui_timeout(self):
        with tempfile.TemporaryDirectory(prefix='hengshi-startup-test-') as folder:
            environment={**os.environ,'HENGSHI_DATA_DIR':folder}
            result=subprocess.run([sys.executable,str(ROOT/'tools/smoke_packaged_backend.py'),
                                   str(ROOT/'electron_backend.py')],cwd=ROOT,env=environment,
                                  capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            self.assertIn('"health": "ok"',result.stdout)
            self.assertIn('"api": "get_state ok"',result.stdout)


if __name__=='__main__':
    unittest.main()
