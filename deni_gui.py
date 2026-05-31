import contextlib
import io
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk
from types import SimpleNamespace

from deni import apply_compact_title_dump
from deni import build_compact_title_dump
from deni import deepseek_fix_dump
from deni import validate_fixed_dump


class DeniApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Deni MP3 Title Cleaner")
        self.geometry("820x560")
        self.minsize(720, 480)
        self.events = queue.Queue()
        self.worker = None

        self.folder_var = tk.StringVar()
        self.limit_var = tk.StringVar()
        self.dry_var = tk.BooleanVar(value=True)
        self.output_var = tk.BooleanVar(value=True)
        self.model_var = tk.StringVar(value="deepseek-v4-flash")

        self.build_ui()
        self.after(100, self.drain_events)

    def build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        folder_row = ttk.Frame(root)
        folder_row.pack(fill=tk.X)
        ttk.Label(folder_row, text="Папка с MP3").pack(side=tk.LEFT)
        ttk.Entry(folder_row, textvariable=self.folder_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        ttk.Button(folder_row, text="Выбрать", command=self.choose_folder).pack(side=tk.LEFT)

        options = ttk.Frame(root)
        options.pack(fill=tk.X, pady=10)
        ttk.Label(options, text="Лимит").pack(side=tk.LEFT)
        ttk.Entry(options, textvariable=self.limit_var, width=8).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Checkbutton(options, text="Только проверить (--dry)", variable=self.dry_var).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Checkbutton(options, text="Сохранить fixed_dump.json", variable=self.output_var).pack(side=tk.LEFT)

        model_row = ttk.Frame(root)
        model_row.pack(fill=tk.X)
        ttk.Label(model_row, text="Модель").pack(side=tk.LEFT)
        ttk.Entry(model_row, textvariable=self.model_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

        buttons = ttk.Frame(root)
        buttons.pack(fill=tk.X, pady=10)
        self.run_button = ttk.Button(buttons, text="Запустить DeepSeek", command=self.start)
        self.run_button.pack(side=tk.LEFT)
        ttk.Button(buttons, text="Очистить лог", command=self.clear_log).pack(side=tk.LEFT, padx=8)

        self.log = tk.Text(root, wrap=tk.WORD, height=20)
        self.log.pack(fill=tk.BOTH, expand=True)
        self.log.insert(tk.END, "Положи deepseek_api_key.txt рядом с exe или deni.py, выбери папку и нажми запуск.\n")

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder_var.set(folder)

    def start(self):
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showerror("Deni", "Выбери папку с MP3.")
            return
        if not os.path.isdir(folder):
            messagebox.showerror("Deni", "Такой папки нет.")
            return

        limit = None
        if self.limit_var.get().strip():
            try:
                limit = int(self.limit_var.get().strip())
            except ValueError:
                messagebox.showerror("Deni", "Лимит должен быть числом.")
                return

        self.run_button.configure(state=tk.DISABLED)
        self.write_log("\n=== Запуск ===\n")
        self.worker = threading.Thread(target=self.run_job, args=(folder, limit), daemon=True)
        self.worker.start()

    def run_job(self, folder, limit):
        try:
            args = SimpleNamespace(
                api_key=None,
                model=self.model_var.get().strip() or "deepseek-v4-flash",
                max_tokens=30000,
                temperature=0.1,
                timeout=120,
                root=None,
                dry=self.dry_var.get(),
            )
            dump_data = build_compact_title_dump(folder, limit)
            self.events.put(("log", f"Найдено MP3: {len(dump_data['files'])}\n"))
            if not dump_data["files"]:
                self.events.put(("done", None))
                return

            fixed_dump = deepseek_fix_dump(dump_data, args)
            validate_fixed_dump(dump_data, fixed_dump)

            if self.output_var.get():
                output = os.path.join(os.getcwd(), "fixed_dump.json")
                with open(output, "w", encoding="utf-8") as f:
                    json.dump(fixed_dump, f, ensure_ascii=False, separators=(",", ":"))
                self.events.put(("log", f"Исправленный дамп сохранён: {output}\n"))

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                apply_compact_title_dump(args, fixed_dump)
            self.events.put(("log", buffer.getvalue()))
            self.events.put(("done", None))
        except Exception as e:
            self.events.put(("error", str(e)))

    def drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.write_log(payload)
                elif kind == "error":
                    self.write_log(f"\nОшибка: {payload}\n")
                    messagebox.showerror("Deni", payload)
                    self.run_button.configure(state=tk.NORMAL)
                elif kind == "done":
                    self.write_log("=== Готово ===\n")
                    self.run_button.configure(state=tk.NORMAL)
        except queue.Empty:
            pass
        self.after(100, self.drain_events)

    def write_log(self, text):
        self.log.insert(tk.END, text)
        self.log.see(tk.END)

    def clear_log(self):
        self.log.delete("1.0", tk.END)


if __name__ == "__main__":
    DeniApp().mainloop()
