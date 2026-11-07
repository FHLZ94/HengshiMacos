import tempfile
import unittest
from pathlib import Path

import installer_core


class InstallerTests(unittest.TestCase):
    def test_install_upgrade_and_uninstall_preserve_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = root/'app.exe'; uninstaller = root/'uninstall.exe'
            target = root/'installed'
            app.write_bytes(b'v1'); uninstaller.write_bytes(b'uninstall')
            installer_core.install(app, uninstaller, target, register=False)
            self.assertEqual((target/installer_core.APP_EXE).read_bytes(),b'v1')
            app.write_bytes(b'v2')
            installer_core.install(app, uninstaller, target, register=False)
            self.assertEqual((target/installer_core.APP_EXE).read_bytes(),b'v2')
            installer_core.uninstall(target, register=False)
            self.assertFalse(target.exists())

    def test_missing_bundle_does_not_modify_existing_install(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); target=root/'installed';target.mkdir()
            (target/installer_core.APP_EXE).write_bytes(b'old')
            with self.assertRaises(FileNotFoundError):
                installer_core.install(root/'missing.exe',root/'uninstall.exe',target,register=False)
            self.assertEqual((target/installer_core.APP_EXE).read_bytes(),b'old')


if __name__=='__main__':
    unittest.main()
