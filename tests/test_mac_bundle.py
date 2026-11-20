import hashlib
import plistlib
from pathlib import Path
import struct
import tempfile
import unittest

from tools.fix_mac_asar_integrity import asar_header_hash,update_bundle


class MacBundleTests(unittest.TestCase):
    def make_asar(self,path,header):
        padding=b'\0'*((-len(header))%4)
        inner_payload=struct.pack('<I',len(header))+header+padding
        inner_pickle=struct.pack('<I',len(inner_payload))+inner_payload
        path.write_bytes(struct.pack('<II',4,4+len(inner_pickle))+inner_pickle+b'payload')

    def test_updates_and_verifies_the_asar_header_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle=Path(folder)/'Hengshi.app'
            resources=bundle/'Contents'/'Resources'
            resources.mkdir(parents=True)
            header=b'{"files":{"main.cjs":{"size":7,"offset":"0"}}}'
            archive=resources/'app.asar'
            self.make_asar(archive,header)
            info=bundle/'Contents'/'Info.plist'
            info.write_bytes(plistlib.dumps({'CFBundleVersion':'1.3.4',
                'ElectronAsarIntegrity':{'Resources/app.asar':{'algorithm':'SHA256','hash':'stale'},
                                         'Resources/default_app.asar':{'algorithm':'SHA256','hash':'keep'}}}))
            expected=hashlib.sha256(header).hexdigest()
            self.assertEqual(asar_header_hash(archive),expected)
            self.assertEqual(update_bundle(bundle),expected)
            with info.open('rb') as stream:result=plistlib.load(stream)
            self.assertEqual(result['ElectronAsarIntegrity']['Resources/app.asar']['hash'],expected)
            self.assertEqual(result['ElectronAsarIntegrity']['Resources/default_app.asar']['hash'],'keep')
            self.assertEqual(result['CFBundleVersion'],'1.3.4')

    def test_rejects_truncated_archive_header(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'app.asar';archive.write_bytes(b'bad')
            with self.assertRaises(ValueError):asar_header_hash(archive)

    def test_header_hash_excludes_pickle_alignment_padding(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'app.asar'
            header=b'{"files":{}}'
            padding=b'\0'*((-len(header))%4)
            inner_payload=struct.pack('<I',len(header))+header+padding
            inner_pickle=struct.pack('<I',len(inner_payload))+inner_payload
            archive.write_bytes(struct.pack('<II',4,4+len(inner_pickle))+inner_pickle+b'data')
            self.assertEqual(asar_header_hash(archive),hashlib.sha256(header).hexdigest())


if __name__=='__main__':unittest.main()
