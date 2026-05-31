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
from deni import APP_ICON_PNG_PATH
from deni import build_compact_title_dump_for_paths
from deni import collect_mp3_paths
from deni import deepseek_fix_dump_batched


class DeniApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Deni MP3 Title Cleaner")
        self.geometry("900x620")
        self.minsize(780, 540)
        self.set_app_icon()
        self.events = queue.Queue()
        self.worker = None

        self.limit_var = tk.StringVar()
        self.dry_var = tk.BooleanVar(value=True)
        self.output_var = tk.BooleanVar(value=True)
        self.model_var = tk.StringVar(value="deepseek-v4-flash")
        self.batch_size_var = tk.StringVar(value="100")
        self.workers_var = tk.StringVar(value="3")

        self.build_ui()
        self.after(100, self.drain_events)

    def set_app_icon(self):
        try:
            self.icon_image = tk.PhotoImage(file=APP_ICON_PNG_PATH)
            self.iconphoto(True, self.icon_image)
        except tk.TclError:
            self.icon_image = None

    def build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        folder_frame = ttk.LabelFrame(root, text="Папки с MP3", padding=8)
        folder_frame.pack(fill=tk.X)
        list_frame = ttk.Frame(folder_frame)
        list_frame.pack(fill=tk.X)
        self.folder_list = tk.Listbox(list_frame, height=4, selectmode=tk.EXTENDED)
        self.folder_list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        folder_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.folder_list.yview)
        folder_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.folder_list.configure(yscrollcommand=folder_scroll.set)

        folder_buttons = ttk.Frame(folder_frame)
        folder_buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(folder_buttons, text="Добавить папку", command=self.add_folder).pack(side=tk.LEFT)
        ttk.Button(folder_buttons, text="Убрать выбранную", command=self.remove_selected_folders).pack(side=tk.LEFT, padx=8)
        ttk.Button(folder_buttons, text="Очистить список", command=self.clear_folders).pack(side=tk.LEFT)

        options = ttk.Frame(root)
        options.pack(fill=tk.X, pady=10)
        ttk.Label(options, text="Лимит").pack(side=tk.LEFT)
        ttk.Entry(options, textvariable=self.limit_var, width=8).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(options, text="Батч").pack(side=tk.LEFT)
        ttk.Entry(options, textvariable=self.batch_size_var, width=6).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(options, text="Потоки").pack(side=tk.LEFT)
        ttk.Entry(options, textvariable=self.workers_var, width=6).pack(side=tk.LEFT, padx=(6, 16))
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
        self.count_button = ttk.Button(buttons, text="Посчитать треки", command=self.start_count)
        self.count_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Очистить лог", command=self.clear_log).pack(side=tk.LEFT, padx=8)

        self.log = tk.Text(root, wrap=tk.WORD, height=20)
        self.log.pack(fill=tk.BOTH, expand=True)
        self.log.insert(tk.END, "Положи deepseek_api_key.txt рядом с exe или deni.py, добавь папки и нажми запуск.\n")

    def add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            existing = set(self.folder_list.get(0, tk.END))
            if folder not in existing:
                self.folder_list.insert(tk.END, folder)

    def remove_selected_folders(self):
        for index in reversed(self.folder_list.curselection()):
            self.folder_list.delete(index)

    def clear_folders(self):
        self.folder_list.delete(0, tk.END)

    def selected_folders(self):
        return list(self.folder_list.get(0, tk.END))

    def start(self):
        folders = self.selected_folders()
        if not folders:
            messagebox.showerror("Deni", "Добавь хотя бы одну папку с MP3.")
            return
        missing = [folder for folder in folders if not os.path.isdir(folder)]
        if missing:
            messagebox.showerror("Deni", f"Такой папки нет: {missing[0]}")
            return

        limit = None
        if self.limit_var.get().strip():
            try:
                limit = int(self.limit_var.get().strip())
            except ValueError:
                messagebox.showerror("Deni", "Лимит должен быть числом.")
                return
        batch_size = self.parse_positive_int(self.batch_size_var.get(), "Батч")
        if batch_size is None:
            return
        workers = self.parse_positive_int(self.workers_var.get(), "Потоки")
        if workers is None:
            return

        self.run_button.configure(state=tk.DISABLED)
        self.count_button.configure(state=tk.DISABLED)
        self.write_log("\n=== Запуск ===\n")
        self.worker = threading.Thread(target=self.run_job, args=(folders, limit, batch_size, workers), daemon=True)
        self.worker.start()

    def parse_positive_int(self, value, label):
        try:
            result = int(value.strip())
        except ValueError:
            messagebox.showerror("Deni", f"{label} должен быть числом.")
            return None
        if result < 1:
            messagebox.showerror("Deni", f"{label} должен быть больше нуля.")
            return None
        return result

    def start_count(self):
        folders = self.selected_folders()
        if not folders:
            messagebox.showerror("Deni", "Добавь хотя бы одну папку с MP3.")
            return
        missing = [folder for folder in folders if not os.path.isdir(folder)]
        if missing:
            messagebox.showerror("Deni", f"Такой папки нет: {missing[0]}")
            return
        self.run_button.configure(state=tk.DISABLED)
        self.count_button.configure(state=tk.DISABLED)
        self.write_log("\n=== Подсчёт треков ===\n")
        threading.Thread(target=self.count_job, args=(folders,), daemon=True).start()

    def count_job(self, folders):
        try:
            count = len(collect_mp3_paths(folders))
            self.events.put(("log", f"Найдено MP3: {count}\n"))
            self.events.put(("done", None))
        except BaseException as e:
            self.events.put(("error", str(e)))

    def run_job(self, folders, limit, batch_size, workers):
        try:
            args = SimpleNamespace(
                api_key=None,
                model=self.model_var.get().strip() or "deepseek-v4-flash",
                max_tokens=30000,
                temperature=0.1,
                timeout=120,
                root=None,
                dry=self.dry_var.get(),
                batch_size=batch_size,
                workers=workers,
            )
            dump_data = build_compact_title_dump_for_paths(folders, limit)
            self.events.put(("log", f"Найдено MP3: {len(dump_data['files'])}\n"))
            if not dump_data["files"]:
                self.events.put(("done", None))
                return

            fixed_dump = deepseek_fix_dump_batched(dump_data, args, self.queue_log)

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
        except BaseException as e:
            self.events.put(("error", str(e)))

    def queue_log(self, text):
        self.events.put(("log", f"{text}\n"))

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
                    self.count_button.configure(state=tk.NORMAL)
                elif kind == "done":
                    self.write_log("=== Готово ===\n")
                    self.run_button.configure(state=tk.NORMAL)
                    self.count_button.configure(state=tk.NORMAL)
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
