"""Prefetch an official Electron artifact and verify its GitHub release digest."""
from pathlib import Path
import hashlib,json,os,re,time
import requests

ROOT=Path(__file__).resolve().parent


def main():
    version=json.loads((ROOT/'electron/node_modules/electron/package.json').read_text(encoding='utf8'))['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Unexpected Electron version')
    headers={'User-Agent':'Hengshi-desktop-build','Accept':'application/vnd.github+json'}
    token=os.environ.get('GITHUB_TOKEN')
    if token:headers['Authorization']='Bearer '+token
    response=requests.get('https://api.github.com/repos/electron/electron/releases/tags/v'+version,headers=headers,timeout=(10,30))
    if response.status_code!=200:raise RuntimeError('Official release metadata unavailable: '+str(response.status_code))
    name=f'electron-v{version}-darwin-x64.zip'
    asset=next(a for a in response.json()['assets'] if a['name']==name)
    expected=asset.get('digest') or ''
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',expected):raise RuntimeError('Official SHA256 digest unavailable')
    destination=ROOT/'electron/resources/electron-runtime.zip';destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_suffix('.partial')
    for attempt in range(4):
        url=asset['browser_download_url'] if attempt%2==0 else asset['url']
        download_headers={'User-Agent':'Hengshi-desktop-build','Accept':'application/octet-stream'}
        if attempt%2 and token:download_headers['Authorization']='Bearer '+token
        try:
            with requests.get(url,headers=download_headers,stream=True,timeout=(10,60)) as stream:
                if stream.status_code!=200:raise RuntimeError('Download HTTP '+str(stream.status_code))
                digest=hashlib.sha256();size=0
                with temporary.open('wb') as output:
                    for chunk in stream.iter_content(1024*1024):
                        if chunk:output.write(chunk);digest.update(chunk);size+=len(chunk)
            if size!=asset['size'] or 'sha256:'+digest.hexdigest()!=expected:raise RuntimeError('Official artifact digest mismatch')
            os.replace(temporary,destination)
            print('Verified official Electron',version,'darwin-x64',size,digest.hexdigest(),flush=True)
            return
        except (requests.RequestException,RuntimeError) as error:
            print('Electron download retry',attempt+1,type(error).__name__,flush=True)
            if temporary.exists():temporary.unlink()
            if attempt==3:raise RuntimeError('Official Electron download could not be verified') from None
            time.sleep(2)


if __name__=='__main__':main()
