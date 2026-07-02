"""
import_tool.py — 可视化数据导入工具
====================================
双击打开，选择其他用户的 data 文件夹，一键导入全部诊断数据。

用法:
    双击 import_tool.pyw (无终端窗口)
    或在终端运行: python tools/import_tool.py
"""

import json
import shutil
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import data_dir as _root_data_dir


class ImportTool:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Manastone 数据导入工具")
        self.root.geometry("560x420")
        self.root.resizable(False, False)
        self._center_window()

        # 样式
        self.root.configure(bg="#0d1117")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#0d1117")
        style.configure("TLabel", background="#0d1117", foreground="#c9d1d9", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=6)
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), foreground="#f0f6fc")
        style.configure("Result.TLabel", font=("Segoe UI", 9))

        self._build_ui()

    def _center_window(self):
        self.root.update_idletasks()
        w, h = 560, 420
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        x = (ws - w) // 2
        y = (hs - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=24)
        main.pack(fill="both", expand=True)

        # 标题
        ttk.Label(main, text="📦 导入其他用户的诊断数据", style="Header.TLabel").pack(anchor="w")
        ttk.Label(main, text="选择对方电脑上的 data 文件夹，一键导入经验 + 归档 + 对话记录",
                  foreground="#8b949e").pack(anchor="w", pady=(4, 16))

        # 分隔线
        ttk.Separator(main, orient="horizontal").pack(fill="x", pady=8)

        # 源目录选择
        ttk.Label(main, text="源数据目录：").pack(anchor="w", pady=(8, 4))
        path_frame = ttk.Frame(main)
        path_frame.pack(fill="x")
        self.path_var = tk.StringVar()
        path_entry = ttk.Entry(path_frame, textvariable=self.path_var, font=("Consolas", 9))
        path_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(path_frame, text="浏览...", command=self._browse).pack(side="right")

        # 预览区域
        ttk.Label(main, text="预览：").pack(anchor="w", pady=(16, 4))
        self.preview_text = tk.Text(main, height=6, bg="#161b22", fg="#c9d1d9",
                                     font=("Consolas", 9), relief="flat", borderwidth=0,
                                     padx=8, pady=8, state="disabled")
        self.preview_text.pack(fill="x")

        # 导入按钮
        self.import_btn = ttk.Button(main, text="开始导入", command=self._do_import, state="disabled")
        self.import_btn.pack(pady=(16, 8))

        # 状态栏
        self.status_var = tk.StringVar(value="请先选择源数据目录")
        ttk.Label(main, textvariable=self.status_var, foreground="#8b949e",
                  style="Result.TLabel").pack(anchor="w")

    def _browse(self):
        path = filedialog.askdirectory(title="选择对方的 data 文件夹",
                                        initialdir=str(Path.home()))
        if path:
            self.path_var.set(path)
            self._preview(path)

    def _preview(self, src_path_str):
        src = Path(src_path_str)
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")

        lines = []
        exp_count = 0
        arch_count = 0
        rec_count = 0

        # 经验库
        shards_dir = src / "experience_shards"
        if shards_dir.is_dir():
            for sf in shards_dir.glob("shard_*.json"):
                try:
                    data = json.loads(sf.read_text(encoding="utf-8"))
                    exp_count += len(data)
                except Exception:
                    pass
            lines.append(f"  诊断经验: {exp_count} 条")
        else:
            lines.append(f"  诊断经验: 无")

        # 归档
        arch_dir = src / "archive"
        if arch_dir.is_dir():
            arch_count = len([f for f in arch_dir.glob("*.json") if f.name != "index.json"])
            lines.append(f"  归档记录: {arch_count} 条")
        else:
            lines.append(f"  归档记录: 无")

        # 对话
        rec_dir = src / "records"
        if rec_dir.is_dir():
            rec_count = len(list(rec_dir.glob("*.json")))
            lines.append(f"  对话记录: {rec_count} 条")
        else:
            lines.append(f"  对话记录: 无")

        total = exp_count + arch_count + rec_count
        lines.append(f"  ─────────────────")
        lines.append(f"  共计可导入: {total} 条数据")

        if total == 0:
            lines.append(f"\n  ⚠️ 所选目录中没有可导入的数据。")
            lines.append(f"  请确认选择了对方 data 文件夹（含 experience_shards/ archive/ records/）。")
            self.import_btn.configure(state="disabled")
        else:
            self.import_btn.configure(state="normal")

        self.preview_text.insert("1.0", "\n".join(lines))
        self.preview_text.configure(state="disabled")
        self.status_var.set(f"预览完成: {total} 条数据待导入")

    def _do_import(self):
        src = self.path_var.get()
        if not src:
            return

        # 先查重
        dest = _root_data_dir()
        idx_path = dest / "experience_index.json"
        existing_count = 0
        if idx_path.exists():
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
            existing_count = len(idx.get("experience_map", {}))

        confirm = messagebox.askyesno(
            "确认导入",
            f"即将从以下目录导入数据：\n\n{src}\n\n"
            f"当前经验库已有 {existing_count} 条经验。\n"
            f"重复项将自动跳过。\n\n确认开始导入？"
        )
        if not confirm:
            return

        # 执行导入
        import subprocess
        tool = str(Path(__file__).resolve().parent / "experience_manager.py")
        try:
            r = subprocess.run(
                ["python", tool, "import", src],
                capture_output=True, text=True, timeout=120,
                cwd=str(Path(__file__).resolve().parent.parent)
            )
            if r.returncode == 0:
                messagebox.showinfo("导入完成", r.stdout.strip() or "导入成功!")
                self.status_var.set("导入完成")
            else:
                messagebox.showerror("导入失败", r.stderr.strip() or "未知错误")
                self.status_var.set("导入失败")
        except Exception as e:
            messagebox.showerror("错误", str(e))
            self.status_var.set(f"错误: {e}")


if __name__ == "__main__":
    app = ImportTool()
    app.root.mainloop()
