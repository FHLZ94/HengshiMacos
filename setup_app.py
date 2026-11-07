"""NEXUS setup wizard."""
from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from installer_core import default_location, install

BG = '#f4f7f8'
PANEL = '#ffffff'
TEXT = '#1b3446'
MUTED = '#6b8291'
ACCENT = '#087e78'


class Setup:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('金融数据与市场监测 · 安装向导')
        self.root.geometry('640x410')
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        icon=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/'nexus.ico'
        if icon.exists(): self.root.iconbitmap(str(icon))
        self.destination = tk.StringVar(value=str(default_location()))
        self.desktop = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value='准备安装')
        self.build()

    def build(self):
        tk.Label(self.root, text='金融数据与市场监测', bg=BG, fg=ACCENT,
                 font=('Segoe UI', 30, 'bold')).pack(anchor='w', padx=32, pady=(24, 0))
        tk.Label(self.root, text='出品：范光旭 · 开发预览版 0.4.0', bg=BG, fg=TEXT,
                 font=('Microsoft YaHei UI', 13)).pack(anchor='w', padx=34, pady=(0, 14))
        tk.Label(self.root, text='选择安装位置', bg=BG, fg=MUTED,
                 font=('Microsoft YaHei UI', 10)).pack(anchor='w', padx=34)
        row = tk.Frame(self.root, bg=BG)
        row.pack(fill='x', padx=32, pady=(7, 12))
        tk.Entry(row, textvariable=self.destination, bg=PANEL, fg=TEXT,
                 insertbackground=TEXT, relief='flat', font=('Segoe UI', 10)).pack(side='left', fill='x', expand=True, ipady=9)
        tk.Button(row, text='浏览…', command=self.browse, bg=PANEL, fg=TEXT,
                  relief='flat', padx=13, pady=8).pack(side='left', padx=(8, 0))
        tk.Checkbutton(self.root, text='创建桌面快捷方式', variable=self.desktop,
                       bg=BG, fg=TEXT, selectcolor=PANEL, activebackground=BG,
                       activeforeground=TEXT).pack(anchor='w', padx=30)
        tk.Label(self.root, text='安装后会显示在 Windows“应用和功能”中。升级保留本地设置与历史数据。',
                 bg=BG, fg=MUTED, wraplength=570, justify='left',
                 font=('Microsoft YaHei UI', 9)).pack(anchor='w', padx=34, pady=(16, 0))
        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(side='bottom', fill='x', padx=32, pady=24)
        tk.Label(bottom, textvariable=self.status, bg=BG, fg=MUTED,
                 font=('Microsoft YaHei UI', 9)).pack(side='left')
        self.button = tk.Button(bottom, text='安装', command=self.start, bg=ACCENT,
                                fg='#ffffff', relief='flat', font=('Microsoft YaHei UI', 11, 'bold'), padx=26, pady=10)
        self.button.pack(side='right')

    def browse(self):
        path = filedialog.askdirectory(initialdir=self.destination.get())
        if path: self.destination.set(path)

    def start(self):
        destination = Path(self.destination.get()).expanduser()
        if not destination.is_absolute():
            messagebox.showerror('路径无效', '请选择完整的安装路径')
            return
        self.button.configure(state='disabled')
        self.status.set('正在安装…')
        make_desktop=self.desktop.get()
        def work():
            try:
                bundle = Path(sys._MEIPASS)
                install(bundle/'金融数据与市场监测.exe', bundle/'卸载金融数据与市场监测.exe', destination, make_desktop)
                self.root.after(0, lambda:self.finish(None))
            except Exception as exc:
                self.root.after(0, lambda error=str(exc):self.finish(error))
        threading.Thread(target=work, daemon=True).start()

    def finish(self, error):
        if error:
            self.status.set('安装失败')
            self.button.configure(state='normal')
            messagebox.showerror('安装失败', error)
        else:
            self.status.set('安装完成')
            messagebox.showinfo('安装完成', '金融数据与市场监测已安装，可从桌面或开始菜单启动。')
            self.root.destroy()


if __name__ == '__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--smoke-install':
        bundle=Path(sys._MEIPASS)
        install(bundle/'金融数据与市场监测.exe',bundle/'卸载金融数据与市场监测.exe',
                Path(sys.argv[2]),desktop=False,register=False)
    else:
        Setup().root.mainloop()
