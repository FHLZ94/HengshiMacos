"""NEXUS uninstaller; self-relocates to remove its installation folder."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
import tkinter as tk
from tkinter import messagebox

from installer_core import installed_location, uninstall


def main():
    target = installed_location()
    if '--from-temp' not in sys.argv and Path(sys.executable).parent.resolve() == target.resolve():
        relocated = Path(tempfile.gettempdir()) / f'NEXUS-Uninstall-{uuid.uuid4().hex}.exe'
        shutil.copy2(sys.executable, relocated)
        subprocess.Popen([str(relocated), '--from-temp'], close_fds=True)
        return
    root = tk.Tk()
    root.withdraw()
    if not messagebox.askyesno('卸载金融数据与市场监测', '确定要卸载金融数据与市场监测吗？\n默认保留本地新闻、设置和持仓数据。'):
        root.destroy(); return
    remove_data = messagebox.askyesno('本地数据', '同时删除本地新闻、设置和持仓数据吗？\n选择“否”会保留这些数据。')
    try:
        uninstall(target, remove_data=remove_data)
        messagebox.showinfo('卸载完成', '金融数据与市场监测已卸载。')
    except Exception as exc:
        messagebox.showerror('卸载失败', str(exc))
    root.destroy()


if __name__ == '__main__':
    main()
