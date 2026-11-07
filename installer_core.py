"""Per-user install, upgrade and uninstall operations for Windows."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import winreg

APP_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\NexusIntelligence'
APP_EXE = '金融数据与市场监测.exe'
UNINSTALL_EXE = '卸载金融数据与市场监测.exe'
VERSION = '0.4.0-preview'


def default_location():
    return Path(os.environ['LOCALAPPDATA']) / 'Programs' / '金融数据与市场监测'


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _shortcuts(target, create_desktop=True, remove=False):
    exe = target / APP_EXE
    script = '$w = New-Object -ComObject WScript.Shell; '
    folders = ['Programs'] + (['Desktop'] if create_desktop else [])
    for folder in folders:
        name = f"$w.SpecialFolders.Item('{folder}')"
        script += f'$path = Join-Path {name} "金融数据与市场监测.lnk"; '
        if remove:
            script += 'Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue; '
        else:
            script += (f'$s = $w.CreateShortcut($path); $s.TargetPath = {_ps_quote(exe)}; '
                       f'$s.WorkingDirectory = {_ps_quote(target)}; '
                       f'$s.IconLocation = {_ps_quote(str(exe)+",0")}; $s.Save(); ')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, creationflags=0x08000000)
    if result.returncode:
        raise OSError(result.stderr.strip() or '无法创建或移除快捷方式')


def _register(target):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, APP_KEY) as key:
        values = {
            'DisplayName': '金融数据与市场监测', 'DisplayVersion': VERSION,
            'Publisher': '范光旭', 'InstallLocation': str(target),
            'DisplayIcon': str(target/APP_EXE),
            'UninstallString': f'"{target/UNINSTALL_EXE}"',
        }
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for name in ('NoModify', 'NoRepair'):
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 1)


def installed_location():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_KEY) as key:
            return Path(winreg.QueryValueEx(key, 'InstallLocation')[0])
    except FileNotFoundError:
        return default_location()


def install(app_source, uninstaller_source, target=None, desktop=True, register=True):
    app_source, uninstaller_source = Path(app_source), Path(uninstaller_source)
    target = Path(target) if target else default_location()
    if not app_source.is_file() or not uninstaller_source.is_file():
        raise FileNotFoundError('安装包缺少应用程序或卸载程序')
    target.mkdir(parents=True, exist_ok=True)
    app_target, uninstall_target = target/APP_EXE, target/UNINSTALL_EXE
    old_app, old_uninstall = target/'.app.previous', target/'.uninstall.previous'
    staged_app, staged_uninstall = target/'.app.pending', target/'.uninstall.pending'
    had_app=app_target.exists()
    app_backed_up=uninstall_backed_up=app_installed=uninstall_installed=False
    try:
        shutil.copy2(app_source, staged_app)
        shutil.copy2(uninstaller_source, staged_uninstall)
        if app_target.exists():
            os.replace(app_target, old_app)
            app_backed_up=True
        if uninstall_target.exists():
            os.replace(uninstall_target, old_uninstall)
            uninstall_backed_up=True
        os.replace(staged_app, app_target)
        app_installed=True
        os.replace(staged_uninstall, uninstall_target)
        uninstall_installed=True
        if register:
            _shortcuts(target, desktop)
            _register(target)
        old_app.unlink(missing_ok=True)
        old_uninstall.unlink(missing_ok=True)
        return target
    except Exception:
        if app_installed: app_target.unlink(missing_ok=True)
        if uninstall_installed: uninstall_target.unlink(missing_ok=True)
        if app_backed_up: os.replace(old_app, app_target)
        if uninstall_backed_up: os.replace(old_uninstall, uninstall_target)
        if register and not had_app:
            try: _shortcuts(target, create_desktop=True, remove=True)
            except OSError: pass
        raise
    finally:
        staged_app.unlink(missing_ok=True)
        staged_uninstall.unlink(missing_ok=True)


def uninstall(target=None, remove_data=False, register=True):
    target = Path(target) if target else installed_location()
    if register:
        _shortcuts(target, create_desktop=True, remove=True)
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, APP_KEY)
        except FileNotFoundError:
            pass
    for name in (APP_EXE, UNINSTALL_EXE, '.app.previous', '.uninstall.previous'):
        (target/name).unlink(missing_ok=True)
    try: target.rmdir()
    except OSError: pass
    if remove_data:
        shutil.rmtree(Path(os.environ['APPDATA'])/'AIMarketIntelligence', ignore_errors=False)
