"""Launch the exact frozen macOS backend and exercise its authenticated local bridge."""
import json
import os
import queue
import threading
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def request(url,token,method=None,args=None,timeout=35):
    payload=None if method is None else json.dumps({'method':method,'args':args or []}).encode()
    headers={'X-Hengshi-Token':token}
    if payload is not None:headers['Content-Type']='application/json'
    req=urllib.request.Request(url,data=payload,headers=headers,method='GET' if payload is None else 'POST')
    with urllib.request.urlopen(req,timeout=timeout) as response:return json.loads(response.read())


def main():
    executable=Path(sys.argv[1]).resolve()
    if not executable.is_file():raise FileNotFoundError(executable)
    with tempfile.TemporaryDirectory(prefix='hengshi-backend-smoke-') as directory:
        token='smoke-'+os.urandom(24).hex()
        env={**os.environ,'HENGSHI_DATA_DIR':directory,'HENGSHI_IPC_TOKEN':token}
        command=[sys.executable,str(executable)] if executable.suffix=='.py' else [str(executable)]
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                 text=True,bufsize=1,env=env,start_new_session=True)
        lines=queue.Queue()
        def read_stdout():
            try:
                for line in process.stdout:lines.put(line)
            finally:lines.put(None)
        reader=threading.Thread(target=read_stdout,daemon=True);reader.start()
        deadline=time.monotonic()+110;port=None;output=[]
        try:
            while time.monotonic()<deadline and process.poll() is None:
                try:line=lines.get(timeout=.5)
                except queue.Empty:continue
                if line is None:break
                output.append(line.rstrip()[:500])
                try:
                    port=json.loads(line)['port']
                    if isinstance(port,int) and 1024<=port<=65535:break
                    port=None
                except (json.JSONDecodeError,KeyError,TypeError):continue
            if port is None:raise RuntimeError(f'Frozen backend produced no valid port before timeout or exit: {output[-12:]}')
            base=f'http://127.0.0.1:{port}'
            if request(base+'/health',token).get('ok') is not True:raise RuntimeError('Authenticated health check failed')
            try:
                request(base+'/health','invalid-smoke-token')
                raise RuntimeError('Health endpoint accepted an invalid token')
            except urllib.error.HTTPError as error:
                if error.code!=403:raise
            state=request(base+'/invoke',token,'get_state',[],timeout=50)
            if not state.get('ok') or not isinstance(state.get('value'),dict):raise RuntimeError('get_state bridge smoke failed')
            print(json.dumps({'startup_seconds':round(110-(deadline-time.monotonic()),2),
                              'health':'ok','api':'get_state ok','watch':len(state['value'].get('watch',[]))},ensure_ascii=False))
        finally:
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            if process.stderr and process.stderr is not subprocess.DEVNULL:process.stderr.close()
            if process.stdout:process.stdout.close()


if __name__=='__main__':main()
