"""Synchronize the macOS bundle's ASAR header hash with its packaged archive."""
from hashlib import sha256
from pathlib import Path
import plistlib
import struct
import sys


def asar_header_hash(path):
    with Path(path).open('rb') as archive:
        prefix=archive.read(8)
        if len(prefix)!=8:
            raise ValueError('ASAR prefix is truncated')
        pickle_size=struct.unpack_from('<I',prefix,4)[0]
        if pickle_size<8 or pickle_size>16*1024*1024:
            raise ValueError('ASAR header size is invalid')
        pickle=archive.read(pickle_size)
    if len(pickle)!=pickle_size:
        raise ValueError('ASAR header is truncated')
    if len(pickle)<8:
        raise ValueError('ASAR nested header is truncated')
    string_size=struct.unpack_from('<I',pickle,4)[0]
    if string_size<=0 or string_size>len(pickle)-8:
        raise ValueError('ASAR header string size is invalid')
    header=pickle[8:8+string_size]
    return sha256(header).hexdigest()


def update_bundle(bundle):
    bundle=Path(bundle)
    contents=bundle/'Contents'
    archive=contents/'Resources'/'app.asar'
    plist_path=contents/'Info.plist'
    if not bundle.is_dir() or not archive.is_file() or not plist_path.is_file():
        raise FileNotFoundError('macOS app bundle, app.asar, or Info.plist is missing')
    with plist_path.open('rb') as source:
        plist=plistlib.load(source)
    integrity=plist.setdefault('ElectronAsarIntegrity',{})
    integrity['Resources/app.asar']={'algorithm':'SHA256','hash':asar_header_hash(archive)}
    temporary=plist_path.with_suffix('.plist.tmp')
    with temporary.open('wb') as destination:
        plistlib.dump(plist,destination,fmt=plistlib.FMT_XML,sort_keys=False)
    temporary.replace(plist_path)
    with plist_path.open('rb') as result:
        check=plistlib.load(result)
    expected=asar_header_hash(archive)
    actual=check['ElectronAsarIntegrity']['Resources/app.asar']['hash']
    if actual!=expected:
        raise ValueError('Info.plist ASAR integrity check failed')
    return expected


if __name__=='__main__':
    if len(sys.argv)!=2:
        raise SystemExit('usage: fix_mac_asar_integrity.py /path/to/Application.app')
    digest=update_bundle(sys.argv[1])
    print(f'Verified app.asar header SHA256: {digest}',flush=True)
