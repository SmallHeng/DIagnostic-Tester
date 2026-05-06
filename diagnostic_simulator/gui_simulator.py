from __future__ import annotations

import asyncio
import logging
import socket
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .gui_common import QueueLogHandler, append_text, configure_root, make_labeled_entry
from .server import DoIPServer


class SimulatorGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        configure_root(root, "ECU Simulator")
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.server: DoIPServer | None = None
        self.thread: threading.Thread | None = None
        self.running = False

        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger().addHandler(QueueLogHandler(self.log_queue))

        self._build()
        self._poll_logs()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self) -> None:
        main = ttk.Frame(self.root, padding=14)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(1, weight=1)
        main.rowconfigure(2, weight=1)

        config = ttk.LabelFrame(main, text="Simulator")
        config.grid(row=0, column=0, columnspan=2, sticky="ew")
        config.columnconfigure(1, weight=1)
        config.columnconfigure(3, weight=1)

        self.host_var = make_labeled_entry(config, "Bind IP", "0.0.0.0", 0)
        self.port_var = make_labeled_entry(config, "Port", "13400", 1)
        initial_config = self._find_default_config()
        self.config_var = tk.StringVar(value=str(initial_config) if initial_config else "")
        ttk.Label(config, text="XML").grid(row=0, column=2, sticky="w", padx=(24, 8), pady=4)
        ttk.Entry(config, textvariable=self.config_var).grid(row=0, column=3, sticky="ew", pady=4)
        ttk.Button(config, text="Browse", command=self._browse_xml).grid(row=0, column=4, padx=(8, 0), pady=4)

        controls = ttk.Frame(main)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 10))
        self.start_button = ttk.Button(controls, text="Start", command=self._start)
        self.stop_button = ttk.Button(controls, text="Stop", command=self._stop, state="disabled")
        self.status_var = tk.StringVar(value="Stopped")
        self.start_button.pack(side="left")
        self.stop_button.pack(side="left", padx=8)
        ttk.Label(controls, textvariable=self.status_var).pack(side="left", padx=16)

        self.log_text = tk.Text(main, height=24, wrap="word", state="disabled")
        self.log_text.grid(row=2, column=0, columnspan=2, sticky="nsew")
        scrollbar = ttk.Scrollbar(main, command=self.log_text.yview)
        scrollbar.grid(row=2, column=2, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        if initial_config:
            append_text(self.log_text, f"XML loaded: {initial_config}")
        else:
            append_text(
                self.log_text,
                "XML not selected. Click Browse and choose mock_data.xml before starting the simulator.",
            )

    def _browse_xml(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("XML", "*.xml"), ("All files", "*.*")])
        if path:
            resolved = Path(path).resolve()
            self.config_var.set(str(resolved))
            append_text(self.log_text, f"XML selected: {resolved}")

    def _start(self) -> None:
        if self.running:
            return
        config_text = self.config_var.get().strip()
        if not config_text:
            self._show_xml_not_found(None)
            return
        config_path = Path(config_text).expanduser()
        if not config_path.is_absolute():
            config_path = (Path.cwd() / config_path).resolve()
        if not config_path.exists():
            self._show_xml_not_found(config_path)
            return
        self.config_var.set(str(config_path))
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("ECU Simulator", "Port must be a number")
            return
        if self._is_port_in_use(self.host_var.get(), port):
            self._show_port_in_use(self.host_var.get(), port)
            return

        self.running = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set("Starting")
        self.thread = threading.Thread(
            target=self._server_thread,
            args=(self.host_var.get(), port, config_path),
            daemon=True,
        )
        self.thread.start()

    def _server_thread(self, host: str, port: int, config_path: Path) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.server = DoIPServer(config_path, host=host, port=port)
        try:
            self.loop.run_until_complete(self.server.serve_forever())
        except OSError as exc:
            if getattr(exc, "winerror", None) == 10048 or getattr(exc, "errno", None) in {48, 98, 10048}:
                self.log_queue.put(self._port_in_use_message(host, port))
            else:
                logging.getLogger("diagnostic_simulator.gui").exception("Simulator failed")
        except Exception:
            logging.getLogger("diagnostic_simulator.gui").exception("Simulator failed")
        finally:
            self.running = False
            self.root.after(0, self._mark_stopped)
            self.loop.close()

    def _stop(self) -> None:
        if self.loop is not None and self.server is not None:
            asyncio.run_coroutine_threadsafe(self.server.stop(), self.loop)
        self.status_var.set("Stopping")

    def _mark_stopped(self) -> None:
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_var.set("Stopped")

    def _find_default_config(self) -> Path | None:
        candidates = [
            Path.cwd() / "mock_data.xml",
            self._application_dir() / "mock_data.xml",
            self._application_dir().parent / "mock_data.xml",
            Path(__file__).resolve().parents[1] / "mock_data.xml",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        return None

    def _application_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    def _show_xml_not_found(self, config_path: Path | None) -> None:
        if config_path is None:
            message = (
                "No XML file is selected. Click Browse and choose mock_data.xml before starting the simulator."
            )
        else:
            message = (
                f"XML file not found: {config_path}\n\n"
                "The value in the XML box must be a real file path. "
                "Click Browse and choose mock_data.xml, or copy mock_data.xml next to the exe."
            )
        append_text(self.log_text, message)
        messagebox.showerror("ECU Simulator", message)

    def _is_port_in_use(self, host: str, port: int) -> bool:
        bind_host = host or "0.0.0.0"
        for socket_type in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
            with socket.socket(socket.AF_INET, socket_type) as sock:
                try:
                    sock.bind((bind_host, port))
                except OSError:
                    return True
                if socket_type == socket.SOCK_STREAM:
                    sock.listen(1)
        return False

    def _show_port_in_use(self, host: str, port: int) -> None:
        message = self._port_in_use_message(host, port)
        append_text(self.log_text, message)
        messagebox.showerror("ECU Simulator", message)

    def _port_in_use_message(self, host: str, port: int) -> str:
        return (
            f"Port {port} on {host} is already in use. "
            "Close the old ecu-simulator/ecu-simulator-gui process, or use another port such as 13401."
        )

    def _poll_logs(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            append_text(self.log_text, line)
            if "listening" in line:
                self.status_var.set("Running")
        self.root.after(150, self._poll_logs)

    def _on_close(self) -> None:
        if self.running:
            self._stop()
        self.root.after(200, self.root.destroy)


def main() -> None:
    root = tk.Tk()
    SimulatorGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
