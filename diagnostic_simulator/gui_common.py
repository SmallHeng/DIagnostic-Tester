from __future__ import annotations

import logging
import queue
import tkinter as tk
from tkinter import ttk


class QueueLogHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue[str]):
        super().__init__()
        self.log_queue = log_queue
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self.log_queue.put(self.format(record))


def append_text(widget: tk.Text, line: str) -> None:
    widget.configure(state="normal")
    widget.insert("end", line + "\n")
    widget.see("end")
    widget.configure(state="disabled")


def make_labeled_entry(parent: ttk.Frame, label: str, value: str, row: int, width: int = 18) -> tk.StringVar:
    variable = tk.StringVar(value=value)
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
    ttk.Entry(parent, textvariable=variable, width=width).grid(row=row, column=1, sticky="ew", pady=4)
    return variable


def configure_root(root: tk.Tk, title: str) -> None:
    root.title(title)
    root.geometry("980x640")
    root.minsize(820, 520)
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
