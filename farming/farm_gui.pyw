from pathlib import Path
import sys
import traceback
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
try:
    from dungeon_farm.gui import App
    App().mainloop()
except Exception as exc:
    (ROOT/'dungeon_farm'/'startup-error.log').write_text(traceback.format_exc(),encoding='utf-8')
    import tkinter as tk
    from tkinter import messagebox
    window=tk.Tk();window.withdraw()
    messagebox.showerror('刷图助手启动失败',str(exc)+'\n\n错误详情已保存在 dungeon_farm/startup-error.log')
    window.destroy()
