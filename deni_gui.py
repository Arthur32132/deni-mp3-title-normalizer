import contextlib
import io
import json
import os
import queue
import random
import threading
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk
from types import SimpleNamespace

from PIL import Image
from PIL import ImageTk

try:
    import pygame
except ImportError:
    pygame = None

from deni import apply_compact_title_dump
from deni import APP_ICON_PNG_PATH
from deni import BACKGROUND_IMAGES_DIR
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
        self.background_enabled = True
        self.background_after = None
        self.background_photo = None
        self.background_image = None
        self.background_paths = self.find_background_images()
        self.music_ready = False
        self.music_after = None
        self.current_track = None

        self.limit_var = tk.StringVar()
        self.dry_var = tk.BooleanVar(value=True)
        self.output_var = tk.BooleanVar(value=True)
        self.model_var = tk.StringVar(value="deepseek-v4-flash")
        self.batch_size_var = tk.StringVar(value="100")
        self.workers_var = tk.StringVar(value="3")

        self.init_music()
        self.build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.drain_events)
        self.after(300, self.start_background_rotation)
        self.after(1000, self.check_music)

    def set_app_icon(self):
        try:
            self.icon_image = tk.PhotoImage(file=APP_ICON_PNG_PATH)
            self.iconphoto(True, self.icon_image)
        except tk.TclError:
            self.icon_image = None

    def build_ui(self):
        self.style = ttk.Style(self)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg="#111111")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self.on_canvas_resize)

        root = tk.Frame(self.canvas, bg="#010101", highlightthickness=0)
        self.content_window = self.canvas.create_window(24, 24, anchor=tk.NW, window=root)

        folder_frame = tk.LabelFrame(root, text="Папки с MP3", padx=8, pady=8, bg="#010101", fg="#ffffff", bd=1, highlightthickness=0)
        folder_frame.pack(fill=tk.X)
        list_frame = tk.Frame(folder_frame, bg="#010101", highlightthickness=0)
        list_frame.pack(fill=tk.X)
        self.folder_list = tk.Listbox(
            list_frame,
            height=4,
            selectmode=tk.EXTENDED,
            bg="#000000",
            fg="#f2f2f2",
            selectbackground="#3b6ea8",
            selectforeground="#ffffff",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#ffffff",
        )
        self.folder_list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        folder_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.folder_list.yview)
        folder_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.folder_list.configure(yscrollcommand=folder_scroll.set)

        folder_buttons = tk.Frame(folder_frame, bg="#010101", highlightthickness=0)
        folder_buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(folder_buttons, text="Добавить папку", command=self.add_folder).pack(side=tk.LEFT)
        ttk.Button(folder_buttons, text="Убрать выбранную", command=self.remove_selected_folders).pack(side=tk.LEFT, padx=8)
        ttk.Button(folder_buttons, text="Очистить список", command=self.clear_folders).pack(side=tk.LEFT)

        options = tk.Frame(root, bg="#010101", highlightthickness=0)
        options.pack(fill=tk.X, pady=10)
        tk.Label(options, text="Лимит", bg="#010101", fg="#ffffff").pack(side=tk.LEFT)
        ttk.Entry(options, textvariable=self.limit_var, width=8).pack(side=tk.LEFT, padx=(6, 16))
        tk.Label(options, text="Батч", bg="#010101", fg="#ffffff").pack(side=tk.LEFT)
        ttk.Entry(options, textvariable=self.batch_size_var, width=6).pack(side=tk.LEFT, padx=(6, 16))
        tk.Label(options, text="Потоки", bg="#010101", fg="#ffffff").pack(side=tk.LEFT)
        ttk.Entry(options, textvariable=self.workers_var, width=6).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Checkbutton(options, text="Только проверить (--dry)", variable=self.dry_var).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Checkbutton(options, text="Сохранить fixed_dump.json", variable=self.output_var).pack(side=tk.LEFT)

        model_row = tk.Frame(root, bg="#010101", highlightthickness=0)
        model_row.pack(fill=tk.X)
        tk.Label(model_row, text="Модель", bg="#010101", fg="#ffffff").pack(side=tk.LEFT)
        ttk.Entry(model_row, textvariable=self.model_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

        buttons = tk.Frame(root, bg="#010101", highlightthickness=0)
        buttons.pack(fill=tk.X, pady=10)
        self.run_button = ttk.Button(buttons, text="Запустить DeepSeek", command=self.start)
        self.run_button.pack(side=tk.LEFT)
        self.count_button = ttk.Button(buttons, text="Посчитать треки", command=self.start_count)
        self.count_button.pack(side=tk.LEFT, padx=(8, 0))
        self.background_button = ttk.Button(buttons, text="Остановить фон", command=self.toggle_background)
        self.background_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Очистить лог", command=self.clear_log).pack(side=tk.LEFT, padx=8)

        self.log = tk.Text(root, wrap=tk.WORD, height=7, bg="#000000", fg="#eeeeee", insertbackground="#eeeeee", relief=tk.FLAT, highlightthickness=0)
        self.log.pack(fill=tk.X, expand=False)
        self.log.insert(tk.END, "Положи deepseek_api_key.txt рядом с exe или deni.py, добавь папки и нажми запуск.\n")

    def add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            existing = set(self.folder_list.get(0, tk.END))
            if folder not in existing:
                self.folder_list.insert(tk.END, folder)
            self.start_random_music()

    def remove_selected_folders(self):
        for index in reversed(self.folder_list.curselection()):
            self.folder_list.delete(index)
        self.start_random_music()

    def clear_folders(self):
        self.folder_list.delete(0, tk.END)
        self.stop_music()

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

    def find_background_images(self):
        exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
        paths = []
        if os.path.isdir(BACKGROUND_IMAGES_DIR):
            for name in os.listdir(BACKGROUND_IMAGES_DIR):
                path = os.path.join(BACKGROUND_IMAGES_DIR, name)
                if os.path.isfile(path) and os.path.splitext(name.lower())[1] in exts:
                    paths.append(path)
        if APP_ICON_PNG_PATH not in paths and os.path.isfile(APP_ICON_PNG_PATH):
            paths.append(APP_ICON_PNG_PATH)
        return paths

    def on_canvas_resize(self, event):
        margin = 24
        self.canvas.coords(self.content_window, margin, margin)
        self.canvas.itemconfigure(self.content_window, width=max(1, event.width - margin * 2))
        self.render_background(self.background_image or self.load_background(APP_ICON_PNG_PATH))

    def load_background(self, path):
        try:
            image = Image.open(path).convert("RGB")
        except OSError:
            image = Image.new("RGB", (1200, 800), "#242424")
        self.background_image = image
        return image

    def fit_background(self, image):
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        ratio = max(width / image.width, height / image.height)
        size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
        resized = image.resize(size, Image.Resampling.LANCZOS)
        left = max(0, (resized.width - width) // 2)
        top = max(0, (resized.height - height) // 2)
        cropped = resized.crop((left, top, left + width, top + height))
        return cropped.point(lambda value: int(value * 0.55))

    def render_background(self, image):
        if image is None:
            return
        fitted = self.fit_background(image)
        self.background_photo = ImageTk.PhotoImage(fitted)
        if not hasattr(self, "background_item"):
            self.background_item = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.background_photo)
            self.canvas.tag_lower(self.background_item)
        else:
            self.canvas.itemconfigure(self.background_item, image=self.background_photo)
            self.canvas.tag_lower(self.background_item)

    def start_background_rotation(self):
        self.render_background(self.load_background(APP_ICON_PNG_PATH))
        self.schedule_next_background()

    def schedule_next_background(self):
        if self.background_after:
            self.after_cancel(self.background_after)
        if self.background_enabled and self.background_paths:
            self.background_after = self.after(random.randint(5000, 10000), self.rotate_background)

    def rotate_background(self):
        if not self.background_enabled:
            return
        previous = self.background_image or self.load_background(APP_ICON_PNG_PATH)
        next_image = self.load_background(random.choice(self.background_paths))
        effect = random.choice(["fade", "pulse", "slide"])
        if effect == "fade":
            self.animate_fade(next_image, previous=previous)
        elif effect == "pulse":
            self.animate_pulse(next_image)
        else:
            self.animate_slide(next_image, previous=previous)

    def animate_fade(self, next_image, step=0, previous=None):
        if previous is None:
            previous = self.background_image or self.load_background(APP_ICON_PNG_PATH)
        if step > 16:
            self.render_background(next_image)
            self.schedule_next_background()
            return
        current = self.fit_background(previous)
        target = self.fit_background(next_image)
        blended = Image.blend(current, target, step / 16)
        self.background_photo = ImageTk.PhotoImage(blended)
        self.canvas.itemconfigure(self.background_item, image=self.background_photo)
        self.after(45, lambda: self.animate_fade(next_image, step + 1, previous))

    def animate_pulse(self, next_image, step=0):
        if step > 12:
            self.render_background(next_image)
            self.schedule_next_background()
            return
        fitted = self.fit_background(next_image)
        factor = 0.45 + abs(6 - step) * 0.04
        pulsed = fitted.point(lambda value: max(0, min(255, int(value * factor))))
        self.background_photo = ImageTk.PhotoImage(pulsed)
        self.canvas.itemconfigure(self.background_item, image=self.background_photo)
        self.after(55, lambda: self.animate_pulse(next_image, step + 1))

    def animate_slide(self, next_image, step=0, previous=None):
        if step > 14:
            self.render_background(next_image)
            self.schedule_next_background()
            return
        old = self.fit_background(previous or self.background_image or self.load_background(APP_ICON_PNG_PATH))
        new = self.fit_background(next_image)
        width = old.width
        offset = int(width * (1 - step / 14))
        frame = Image.new("RGB", old.size)
        frame.paste(old, (-width + offset, 0))
        frame.paste(new, (offset, 0))
        self.background_photo = ImageTk.PhotoImage(frame)
        self.canvas.itemconfigure(self.background_item, image=self.background_photo)
        self.after(45, lambda: self.animate_slide(next_image, step + 1, previous))

    def toggle_background(self):
        self.background_enabled = not self.background_enabled
        if self.background_enabled:
            self.background_button.configure(text="Остановить фон")
            self.schedule_next_background()
        else:
            if self.background_after:
                self.after_cancel(self.background_after)
                self.background_after = None
            self.background_button.configure(text="Включить фон")
            self.render_background(self.load_background(APP_ICON_PNG_PATH))

    def init_music(self):
        if pygame is None:
            return
        try:
            pygame.mixer.init()
            self.music_ready = True
        except pygame.error:
            self.music_ready = False

    def start_random_music(self):
        if not self.music_ready:
            return
        tracks = collect_mp3_paths(self.selected_folders())
        if not tracks:
            return
        random.shuffle(tracks)
        for track in tracks[:20]:
            try:
                pygame.mixer.music.load(track)
                pygame.mixer.music.play()
                self.current_track = track
                self.queue_log(f"Музыка: {os.path.basename(track)}")
                return
            except pygame.error:
                continue

    def stop_music(self):
        if self.music_ready:
            pygame.mixer.music.stop()
        self.current_track = None

    def check_music(self):
        if self.music_ready and self.selected_folders() and not pygame.mixer.music.get_busy():
            self.start_random_music()
        self.music_after = self.after(2000, self.check_music)

    def on_close(self):
        if self.background_after:
            self.after_cancel(self.background_after)
        if self.music_after:
            self.after_cancel(self.music_after)
        self.stop_music()
        self.destroy()


if __name__ == "__main__":
    DeniApp().mainloop()
