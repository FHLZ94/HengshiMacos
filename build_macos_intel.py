"""Build the Electron Intel macOS DMG on an x86_64 Mac."""
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
VENV = ROOT / '.venv-macos-intel'
PYTHON = VENV / 'bin' / 'python'


def run(*args, cwd=ROOT):
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True)


def make_icon():
    source = ROOT / 'nexus.png'
    if not source.is_file():
        raise FileNotFoundError(source)
    icon = ROOT / 'nexus.icns'
    with tempfile.TemporaryDirectory(prefix='hengshi-icon-') as folder:
        iconset = Path(folder) / 'AppIcon.iconset'
        iconset.mkdir()
        sizes = [(16, ''), (16, '@2x'), (32, ''), (32, '@2x'),
                 (128, ''), (128, '@2x'), (256, ''), (256, '@2x'),
                 (512, ''), (512, '@2x')]
        for base, suffix in sizes:
            pixels = base * (2 if suffix else 1)
            run('sips', '-z', pixels, pixels, source, '--out',
                iconset / f'icon_{base}x{base}{suffix}.png')
        run('iconutil', '-c', 'icns', iconset, '-o', icon)
    return icon


def main():
    if sys.platform != 'darwin' or platform.machine() != 'x86_64':
        raise SystemExit('请在 Intel Mac 或 Intel macOS 构建机上运行。')
    if sys.version_info[:2] != (3, 11):
        raise SystemExit('请使用 Python 3.11。')
    if not PYTHON.exists():
        run(sys.executable, '-m', 'venv', VENV)
    run(PYTHON, '-m', 'pip', 'install', '-r', 'requirements-backend.txt')
    run(PYTHON, '-m', 'unittest', 'discover', '-s', 'tests')
    run(PYTHON, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--console',
        '--target-arch', 'x86_64', '--name', 'hengshi-backend',
        '--add-data', 'assets/sp500_constituents.csv:assets', 'electron_backend.py')
    backend_dir = ROOT / 'electron' / 'resources' / 'backend'
    backend_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT/'dist'/'hengshi-backend',backend_dir/'hengshi-backend',dirs_exist_ok=True)
    (backend_dir/'hengshi-backend'/'hengshi-backend').chmod(0o755)
    run(PYTHON,'tools/smoke_packaged_backend.py',backend_dir/'hengshi-backend'/'hengshi-backend')
    icon_dir = ROOT / 'electron' / 'build'
    icon_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(make_icon(), icon_dir / 'icon.icns')
    run('pnpm', 'install', '--frozen-lockfile', cwd=ROOT / 'electron')
    run('pnpm', 'run', 'check', cwd=ROOT / 'electron')
    run('pnpm', 'run', 'dist:mac', cwd=ROOT / 'electron')
    import json
    version=json.loads((ROOT/'electron'/'package.json').read_text(encoding='utf8'))['version']
    print(ROOT / 'electron' / 'dist' / f'衡势-{version}-macOS-Intel.dmg')


if __name__ == '__main__':
    main()
