"""Build the Windows app, uninstaller and self-contained setup program."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
VENV=ROOT/'.venv'
PYTHON=VENV/'Scripts'/'python.exe'


def run(*args):
    subprocess.run([str(arg) for arg in args],check=True,cwd=ROOT)


def build(name,script,extra=(),dist='dist/release'):
    run(PYTHON,'-m','PyInstaller','--noconfirm','--windowed','--onefile',
        '--icon','nexus.ico','--name',name,'--distpath',dist,*extra,script)


def main():
    if not PYTHON.exists():
        run(sys.executable,'-m','venv',VENV)
    run(PYTHON,'-m','pip','install','-r','requirements.txt')
    build('衡势','desktop.py',
          ('--add-data','frontend;frontend','--add-data','assets/sp500_constituents.csv;assets',
           '--version-file','version_info.txt'))
    compiler=Path.home()/'AppData'/'Local'/'Programs'/'Inno Setup 6'/'ISCC.exe'
    if not compiler.is_file():
        raise FileNotFoundError('Inno Setup 6 编译器未安装')
    run(compiler,'installer.iss')
    print(ROOT/'installer'/'衡势-安装包.exe')


if __name__=='__main__':
    main()
