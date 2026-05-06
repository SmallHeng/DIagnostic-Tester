from __future__ import annotations

import asyncio
import contextlib
import queue
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .gui_common import append_text
from odx import OdxDatabase, decode_negative_response, load_odx
from .tester import TesterClient, parse_hex_command


@dataclass(frozen=True)
class QuickAction:
    label: str
    request: str


class TesterGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._configure_root()
        self.odx_source_path: Path | None = None
        self.odx_database = self._load_odx_database()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.client: TesterClient | None = None
        self.connected = False
        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.thread: threading.Thread | None = None

        self.dtc_rows: dict[str, tuple[str, str, str, str]] = {}
        self.signal_definitions = self._signal_definitions_from_odx()
        self.flash_directory = self._external_base_dir() / "Flash File"
        self.flash_ecus = self._ecus_from_odx()
        self.flash_start_address = 0x00010000
        self.flash_block_size = 0x10
        self.selected_flash_file: Path | None = None
        self.loaded_flash_files: list[Path] = []
        self.flash_file_sizes: dict[Path, int] = {}
        self.selected_signals: set[str] = {"F190"}
        self.signal_values: dict[str, str] = {}
        self.structure_field_vars: dict[str, tk.StringVar] = {}
        self.service_input_vars: dict[str, tk.StringVar] = {}
        self.service_structure_fields: dict[str, tuple[str, str]] = {}
        self.active_structure_did: str | None = None
        self.odx_path_var = tk.StringVar(value=str(self.odx_source_path) if self.odx_source_path else "")
        self.last_response_var = tk.StringVar(value="-")
        self.status_var = tk.StringVar(value="DISCONNECTED")
        self.session_var = tk.StringVar(value="Default")
        self.security_var = tk.StringVar(value="Locked")
        self.vin_var = tk.StringVar(value="-")
        self.selected_page = tk.StringVar(value="Overview")

        self._build()
        self._start_event_loop_thread()
        self._poll_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(0, self._show_main_window)

    def _configure_root(self) -> None:
        self.root.title("After-Sales Diagnostic Tester")
        self.root.geometry("1600x860")
        self.root.minsize(1360, 760)
        self.root.configure(bg="#EDF1F5")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background="#EDF1F5", foreground="#17212B")
        style.configure("Root.TFrame", background="#EDF1F5")
        style.configure("Top.TFrame", background="#17212B")
        style.configure("Sidebar.TFrame", background="#23313F")
        style.configure("Sidebar.TButton", background="#23313F", foreground="#EAF0F6", borderwidth=0, padding=(14, 10), anchor="w")
        style.map("Sidebar.TButton", background=[("active", "#2E4256")])
        style.configure("Card.TFrame", background="#FFFFFF", relief="solid", borderwidth=1)
        style.configure("Panel.TLabelframe", background="#FFFFFF", borderwidth=1, relief="solid")
        style.configure("Panel.TLabelframe.Label", background="#FFFFFF", foreground="#17212B", font=("Segoe UI Semibold", 10))
        style.configure("Title.TLabel", background="#17212B", foreground="#FFFFFF", font=("Segoe UI Semibold", 14))
        style.configure("Status.TLabel", background="#17212B", foreground="#D9E6F2")
        style.configure("Metric.TLabel", background="#FFFFFF", foreground="#17212B", font=("Segoe UI Semibold", 15))
        style.configure("Muted.TLabel", background="#FFFFFF", foreground="#607080")
        style.configure("Accent.TButton", padding=(14, 8), font=("Segoe UI Semibold", 10))
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10))

    def _external_base_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            if exe_dir.name.lower() == "dist":
                return exe_dir.parent
            if exe_dir.parent.name.lower() == "dist":
                return exe_dir.parent.parent
            return exe_dir
        return Path(__file__).resolve().parents[1]

    def _load_odx_database(self) -> OdxDatabase:
        for path in (self._external_base_dir() / "odx_data.pdx", self._external_base_dir() / "odx_data.xml"):
            if not path.exists():
                continue
            try:
                database = load_odx(path)
                self.odx_source_path = path
                return database
            except Exception as exc:
                messagebox.showwarning("Tester", f"ODX load failed, using built-in defaults: {exc}")
        return OdxDatabase()

    def _signal_definitions_from_odx(self) -> dict[str, tuple[str, str]]:
        if self.odx_database.dids:
            return {did.did: (did.name, did.description) for did in self.odx_database.dids}
        return {
            "F190": ("VIN", "Vehicle identification number"),
            "F187": ("Counter", "Sequential counter sample"),
            "F18C": ("Slow Data", "Pending response sample"),
        }

    def _ecus_from_odx(self) -> dict[str, tuple[str, str, str]]:
        if self.odx_database.ecus:
            return {
                f"0x{int(ecu.address, 16):04X}": (ecu.name, ecu.role, ecu.access)
                for ecu in self.odx_database.ecus
            }
        return {
            "0x1001": ("Gateway", "gateway", "direct"),
            "0x1002": ("BodyControlModule", "ecu", "proxied"),
        }

    def _quick_actions(self) -> tuple[QuickAction, ...]:
        if self.odx_database.quick_actions:
            return tuple(QuickAction(action.label, action.request) for action in self.odx_database.quick_actions)
        return (
            QuickAction("Read VIN", "22 F1 90"),
            QuickAction("Extended Session", "10 03"),
            QuickAction("Request Seed", "27 01"),
            QuickAction("Send Key", "27 02 87 65 43 21"),
            QuickAction("Read DTC", "19 02 FF"),
            QuickAction("Clear DTC", "14 FF FF FF"),
        )

    def _debug_flash(self, message: str) -> None:
        try:
            log_path = self._external_base_dir() / "tester_gui_debug.log"
            if log_path.exists() and log_path.stat().st_size > 1_000_000:
                log_path.unlink()
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            thread_name = threading.current_thread().name
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{timestamp} [{thread_name}] FLASH_LOAD {message}\n")
        except Exception:
            pass

    def _show_main_window(self) -> None:
        try:
            self.root.update_idletasks()
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            width = min(1600, max(1360, screen_width - 80))
            height = min(860, max(760, screen_height - 100))
            left = max(0, (screen_width - width) // 2)
            top = max(0, (screen_height - height) // 2)
            geometry = f"{width}x{height}+{left}+{top}"
            self.root.geometry(geometry)
            self.root.attributes("-alpha", 1.0)
            self.root.deiconify()
            self.root.state("normal")
            self.root.lift()
            self.root.focus_force()
            self.root.attributes("-topmost", True)
            self.root.update_idletasks()
            self.root.after(500, self._release_topmost)
        except Exception:
            messagebox.showerror("Tester", "Failed to show Tester window")

    def _release_topmost(self) -> None:
        with contextlib.suppress(Exception):
            self.root.attributes("-topmost", False)

    def _build(self) -> None:
        shell = ttk.Frame(self.root, style="Root.TFrame")
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(1, weight=1)
        shell.columnconfigure(2, weight=0)
        shell.rowconfigure(1, weight=1)

        self._build_top_bar(shell)
        self._build_sidebar(shell)
        self._build_workspace(shell)
        self._build_live_log_panel(shell)

    def _build_top_bar(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Top.TFrame", padding=(16, 12))
        top.grid(row=0, column=0, columnspan=3, sticky="ew")
        for index in range(12):
            top.columnconfigure(index, weight=0)
        top.columnconfigure(11, weight=1)

        ttk.Label(top, text="After-Sales Diagnostic Tester", style="Title.TLabel").grid(row=0, column=0, padx=(0, 22), sticky="w")
        self.host_var = tk.StringVar(value="127.0.0.1")
        self.port_var = tk.StringVar(value="13400")
        self.source_var = tk.StringVar(value="0x0E80")
        self.target_var = tk.StringVar(value="0x1001")

        self._top_entry(top, "Simulator IP", self.host_var, 1, 16)
        self._top_entry(top, "Port", self.port_var, 3, 8)
        self._top_entry(top, "Source", self.source_var, 5, 10)
        self._top_entry(top, "Target", self.target_var, 7, 10)

        self.connect_button = ttk.Button(top, text="Connect", style="Accent.TButton", command=self._connect)
        self.disconnect_button = ttk.Button(top, text="Disconnect", command=self._disconnect, state="disabled")
        self.connect_button.grid(row=0, column=9, padx=(14, 6))
        self.disconnect_button.grid(row=0, column=10, padx=(0, 12))
        ttk.Label(top, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=11, sticky="e")

    def _top_entry(self, parent: ttk.Frame, label: str, variable: tk.StringVar, column: int, width: int) -> None:
        ttk.Label(parent, text=label, style="Status.TLabel").grid(row=0, column=column, padx=(0, 6), sticky="e")
        ttk.Entry(parent, textvariable=variable, width=width).grid(row=0, column=column + 1, sticky="w")

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        sidebar = ttk.Frame(parent, style="Sidebar.TFrame", padding=(10, 14))
        sidebar.grid(row=1, column=0, sticky="ns")
        pages = ("Overview", "DTC", "Signal", "Routine", "Flash", "Settings")
        for row, page in enumerate(pages):
            button = ttk.Button(
                sidebar,
                text=page,
                style="Sidebar.TButton",
                command=lambda value=page: self._show_page(value),
            )
            button.grid(row=row, column=0, sticky="ew", pady=(0, 4))
        self.show_heartbeat_var = tk.BooleanVar(value=True)
        self.show_live_log_var = tk.BooleanVar(value=True)

    def _build_workspace(self, parent: ttk.Frame) -> None:
        self.workspace = ttk.Frame(parent, style="Root.TFrame", padding=(12, 12, 10, 8))
        self.workspace.grid(row=1, column=1, sticky="nsew")
        self.workspace.columnconfigure(0, weight=1)
        self.workspace.rowconfigure(0, weight=1)

        self.pages: dict[str, ttk.Frame] = {}
        for name in ("Overview", "DTC", "Signal", "Routine", "Flash", "Settings"):
            frame = ttk.Frame(self.workspace, style="Root.TFrame")
            frame.grid(row=0, column=0, sticky="nsew")
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            self.pages[name] = frame

        self._build_overview(self.pages["Overview"])
        self._build_dtc_page(self.pages["DTC"])
        self._build_signal_page(self.pages["Signal"])
        self._build_routine_page(self.pages["Routine"])
        self._build_flash_page(self.pages["Flash"])
        self._build_settings_page(self.pages["Settings"])
        self._show_page("Overview")

    def _build_overview(self, parent: ttk.Frame) -> None:
        grid = ttk.Frame(parent, style="Root.TFrame")
        grid.grid(row=0, column=0, sticky="nsew")
        for col in range(4):
            grid.columnconfigure(col, weight=1, uniform="overview")
        grid.rowconfigure(4, weight=1)

        self._metric_card(grid, "Connection", self.status_var, 0, 0)
        self._metric_card(grid, "VIN", self.vin_var, 0, 1)
        self._metric_card(grid, "Session", self.session_var, 0, 2)
        self._metric_card(grid, "Security", self.security_var, 0, 3)

        actions = ttk.LabelFrame(grid, text="Guided Actions", style="Panel.TLabelframe", padding=12)
        actions.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        self.quick_actions_frame = actions
        self._refresh_quick_actions()

        manual = ttk.LabelFrame(grid, text="Custom Request", style="Panel.TLabelframe", padding=12)
        manual.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        manual.columnconfigure(0, weight=1)
        self.request_var = tk.StringVar(value="22 F1 90")
        ttk.Entry(manual, textvariable=self.request_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(manual, text="Send", command=self._send).grid(row=0, column=1, padx=(10, 0))

        response = ttk.LabelFrame(grid, text="Last Response", style="Panel.TLabelframe", padding=12)
        response.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        response.columnconfigure(0, weight=1)
        ttk.Label(response, textvariable=self.last_response_var, style="Metric.TLabel", wraplength=960).grid(
            row=0,
            column=0,
            sticky="w",
        )

        detail = ttk.Frame(grid, style="Root.TFrame")
        detail.grid(row=4, column=0, columnspan=4, sticky="nsew", pady=(14, 0))
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(0, weight=1)

        ecu_panel = ttk.LabelFrame(detail, text="ECU Targets", style="Panel.TLabelframe", padding=10)
        ecu_panel.grid(row=0, column=0, sticky="nsew")
        ecu_panel.rowconfigure(0, weight=1)
        ecu_panel.columnconfigure(0, weight=1)
        self.ecu_tree = ttk.Treeview(ecu_panel, columns=("address", "role", "access"), show="tree headings", height=8)
        self.ecu_tree.heading("#0", text="ECU")
        self.ecu_tree.heading("address", text="Address")
        self.ecu_tree.heading("role", text="Role")
        self.ecu_tree.heading("access", text="Access")
        self.ecu_tree.column("#0", width=180, minwidth=140)
        self.ecu_tree.column("address", width=86, minwidth=76, anchor="center")
        self.ecu_tree.column("role", width=82, minwidth=70, anchor="center")
        self.ecu_tree.column("access", width=92, minwidth=78, anchor="center")
        self.ecu_tree.grid(row=0, column=0, sticky="nsew")
        self._refresh_ecu_targets()

    def _metric_card(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int, column: int) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        card.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 7, 0 if column == 3 else 7))
        ttk.Label(card, text=label, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(card, textvariable=variable, style="Metric.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))

    def _build_dtc_page(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(parent, style="Root.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.dtc_mask_var = tk.StringVar(value="FF")
        ttk.Label(toolbar, text="Status Mask").pack(side="left")
        ttk.Entry(toolbar, textvariable=self.dtc_mask_var, width=8).pack(side="left", padx=(6, 12))
        ttk.Button(toolbar, text="Read DTC", command=self._read_dtc).pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="Clear DTC", command=self._clear_dtc).pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="Snapshot", command=self._read_selected_snapshot).pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="Extended Data", command=self._read_selected_extended).pack(side="left")

        table_frame = ttk.LabelFrame(parent, text="Fault Memory", style="Panel.TLabelframe", padding=8)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        columns = ("status", "severity", "memory", "description")
        self.dtc_table = ttk.Treeview(table_frame, columns=columns, show="tree headings")
        self.dtc_table.heading("#0", text="DTC")
        self.dtc_table.heading("status", text="Status")
        self.dtc_table.heading("severity", text="Severity")
        self.dtc_table.heading("memory", text="Memory")
        self.dtc_table.heading("description", text="Description")
        self.dtc_table.column("#0", width=130, anchor="center")
        self.dtc_table.column("status", width=90, anchor="center")
        self.dtc_table.column("severity", width=90, anchor="center")
        self.dtc_table.column("memory", width=100, anchor="center")
        self.dtc_table.column("description", width=360)
        self.dtc_table.grid(row=0, column=0, sticky="nsew")
        ttk.Scrollbar(table_frame, command=self.dtc_table.yview).grid(row=0, column=1, sticky="ns")
        self.dtc_table.configure(yscrollcommand=lambda *args: None)

    def _build_signal_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=2)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=0)
        selector = ttk.LabelFrame(parent, text="Signal List", style="Panel.TLabelframe", padding=10)
        selector.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        selector.rowconfigure(1, weight=1)
        selector.columnconfigure(0, weight=1)
        self.signal_list_table = ttk.Treeview(selector, columns=("did", "name"), show="tree headings", selectmode="browse")
        self.signal_list_table.heading("#0", text="Select")
        self.signal_list_table.heading("did", text="DID")
        self.signal_list_table.heading("name", text="Signal name")
        self.signal_list_table.column("#0", width=72, minwidth=64, anchor="center")
        self.signal_list_table.column("did", width=110, minwidth=90, anchor="center")
        self.signal_list_table.column("name", width=260, minwidth=160)
        self.signal_list_table.grid(row=1, column=0, sticky="nsew")
        self.signal_list_table.bind("<ButtonRelease-1>", self._toggle_signal_selection)
        ttk.Button(selector, text="Read Selected", command=self._read_selected_signals).grid(row=2, column=0, sticky="ew", pady=(12, 0))

        results = ttk.LabelFrame(parent, text="Selected Signals", style="Panel.TLabelframe", padding=8)
        results.grid(row=0, column=1, sticky="nsew")
        results.rowconfigure(0, weight=1)
        results.columnconfigure(0, weight=1)
        self.signal_table = ttk.Treeview(results, columns=("value",), show="tree headings")
        self.signal_table.heading("#0", text="DID")
        self.signal_table.heading("value", text="Value")
        self.signal_table.column("#0", width=120, minwidth=100, anchor="center")
        self.signal_table.column("value", width=360, minwidth=180)
        self.signal_table.grid(row=0, column=0, sticky="nsew")
        ttk.Scrollbar(results, command=self.signal_table.yview).grid(row=0, column=1, sticky="ns")
        self.signal_table.configure(yscrollcommand=lambda *args: None)
        self._refresh_signal_list()

        tools = ttk.Frame(parent, style="Root.TFrame")
        tools.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        tools.columnconfigure(0, weight=1)
        tools.columnconfigure(1, weight=1)

        self.structure_panel = ttk.LabelFrame(tools, text="DID Structure Fields", style="Panel.TLabelframe", padding=10)
        self.structure_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.structure_panel.columnconfigure(1, weight=1)

        self.service_panel = ttk.LabelFrame(tools, text="ODX Service Request Builder", style="Panel.TLabelframe", padding=10)
        self.service_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.service_panel.columnconfigure(1, weight=1)
        self.service_var = tk.StringVar(value="")
        ttk.Label(self.service_panel, text="Service").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.service_combo = ttk.Combobox(self.service_panel, textvariable=self.service_var, state="readonly")
        self.service_combo.grid(row=0, column=1, sticky="ew")
        self.service_combo.bind("<<ComboboxSelected>>", self._render_service_fields)
        self.service_fields_frame = ttk.Frame(self.service_panel)
        self.service_fields_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.service_fields_frame.columnconfigure(1, weight=1)
        service_buttons = ttk.Frame(self.service_panel)
        service_buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(service_buttons, text="Build", command=self._build_encoded_service_request).pack(side="left", padx=(0, 8))
        ttk.Button(service_buttons, text="Send", command=self._send_encoded_service_request).pack(side="left")
        self._refresh_service_builder()

    def _build_routine_page(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(parent, style="Root.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        default_routine = self.odx_database.routines[0] if self.odx_database.routines else None
        self.routine_var = tk.StringVar(value=default_routine.routine_id if default_routine else "FF00")
        self.routine_type_var = tk.StringVar(value=default_routine.control if default_routine else "01")
        ttk.Label(toolbar, text="Control").pack(side="left")
        ttk.Combobox(toolbar, textvariable=self.routine_type_var, values=("01", "02", "03"), width=6, state="readonly").pack(side="left", padx=(6, 12))
        ttk.Label(toolbar, text="Routine ID").pack(side="left")
        ttk.Entry(toolbar, textvariable=self.routine_var, width=10).pack(side="left", padx=(6, 12))
        ttk.Button(toolbar, text="Execute", command=self._execute_routine).pack(side="left")

        self.routine_log = tk.Text(parent, wrap="word", state="disabled", bg="#FFFFFF", relief="solid", height=18)
        self.routine_log.grid(row=1, column=0, sticky="nsew")

    def _build_flash_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=2)
        parent.columnconfigure(1, weight=3)
        parent.rowconfigure(0, weight=1)

        ecu_panel = ttk.LabelFrame(parent, text="ECU List", style="Panel.TLabelframe", padding=8)
        ecu_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ecu_panel.rowconfigure(0, weight=1)
        ecu_panel.columnconfigure(0, weight=1)
        self.flash_ecu_table = ttk.Treeview(ecu_panel, columns=("address", "role", "access"), show="tree headings")
        self.flash_ecu_table.heading("#0", text="ECU")
        self.flash_ecu_table.heading("address", text="Address")
        self.flash_ecu_table.heading("role", text="Role")
        self.flash_ecu_table.heading("access", text="Access")
        self.flash_ecu_table.column("#0", width=170, minwidth=130)
        self.flash_ecu_table.column("address", width=84, minwidth=76, anchor="center")
        self.flash_ecu_table.column("role", width=74, minwidth=64, anchor="center")
        self.flash_ecu_table.column("access", width=84, minwidth=76, anchor="center")
        self.flash_ecu_table.grid(row=0, column=0, sticky="nsew")
        self._refresh_flash_ecu_table()
        self.flash_ecu_table.bind("<<TreeviewSelect>>", self._on_flash_ecu_selected)

        file_panel = ttk.LabelFrame(parent, text="Flash Files", style="Panel.TLabelframe", padding=10)
        file_panel.grid(row=0, column=1, sticky="nsew")
        file_panel.columnconfigure(0, weight=1)
        file_panel.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(file_panel, style="Root.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(0, weight=1)
        self.flash_folder_var = tk.StringVar(value=str(self.flash_directory))
        ttk.Label(toolbar, textvariable=self.flash_folder_var, width=52).grid(row=0, column=0, sticky="w")
        ttk.Button(toolbar, text="Load File", command=self._load_flash_file).grid(row=0, column=1, padx=(10, 0))
        ttk.Button(toolbar, text="Refresh", command=self._refresh_flash_files).grid(row=0, column=2, padx=(8, 0))

        self.flash_file_table = ttk.Treeview(file_panel, columns=("size", "modified"), show="tree headings")
        self.flash_file_table.heading("#0", text="File")
        self.flash_file_table.heading("size", text="Size")
        self.flash_file_table.heading("modified", text="Modified")
        self.flash_file_table.column("#0", width=320, minwidth=220)
        self.flash_file_table.column("size", width=90, anchor="center")
        self.flash_file_table.column("modified", width=140, anchor="center")
        self.flash_file_table.grid(row=1, column=0, sticky="nsew")
        ttk.Scrollbar(file_panel, command=self.flash_file_table.yview).grid(row=1, column=1, sticky="ns")
        self.flash_file_table.configure(yscrollcommand=lambda *args: None)
        self.flash_file_table.bind("<<TreeviewSelect>>", self._on_flash_file_selected)

        info = ttk.Frame(file_panel, style="Root.TFrame")
        info.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        info.columnconfigure(0, weight=1)
        self.flash_file_info_var = tk.StringVar(value="No flash file selected")
        self.flash_status_var = tk.StringVar(value="Ready")
        ttk.Label(info, textvariable=self.flash_file_info_var).grid(row=0, column=0, sticky="w")
        ttk.Label(info, textvariable=self.flash_status_var).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.flash_progress = ttk.Progressbar(info, mode="determinate", maximum=100)
        self.flash_progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(info, text="Flash", style="Accent.TButton", command=self._start_flash).grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e",
            padx=(12, 0),
        )
        self._refresh_flash_files()

    def _build_settings_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        odx_panel = ttk.LabelFrame(parent, text="ODX / PDX Database", style="Panel.TLabelframe", padding=16)
        odx_panel.grid(row=0, column=0, sticky="ew")
        odx_panel.columnconfigure(1, weight=1)
        ttk.Label(odx_panel, text="Current file").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(odx_panel, textvariable=self.odx_path_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(odx_panel, text="Choose ODX/PDX", command=self._choose_odx_file).grid(row=0, column=2, padx=(10, 0))
        ttk.Button(odx_panel, text="Reload", command=self._reload_odx_file).grid(row=0, column=3, padx=(8, 0))
        ttk.Label(
            odx_panel,
            text="Loading a new file rebuilds the signal, ECU, routine, and quick-action views for this session.",
            wraplength=820,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(10, 0))

        panel = ttk.LabelFrame(parent, text="Display Settings", style="Panel.TLabelframe", padding=16)
        panel.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text="Live Log", style="Metric.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            panel,
            text="Show live communication panel on the right",
            variable=self.show_live_log_var,
            command=self._toggle_live_log,
        ).grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Checkbutton(
            panel,
            text="Show Tester Present heartbeat in logs",
            variable=self.show_heartbeat_var,
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))

        note = ttk.LabelFrame(parent, text="Current Behavior", style="Panel.TLabelframe", padding=16)
        note.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        ttk.Label(
            note,
            text=(
                "Request and Response logs are recorded globally. "
                "Hiding the live panel only changes the layout for the current session."
            ),
            wraplength=760,
        ).grid(row=0, column=0, sticky="w")

    def _choose_odx_file(self) -> None:
        initial_dir = self.odx_source_path.parent if self.odx_source_path else self._external_base_dir()
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Choose ODX/PDX file",
            initialdir=str(initial_dir),
            filetypes=(("ODX / PDX", "*.odx *.xml *.pdx"), ("ODX", "*.odx"), ("PDX", "*.pdx"), ("XML", "*.xml"), ("All files", "*.*")),
        )
        if selected:
            self._apply_odx_file(Path(selected))

    def _reload_odx_file(self) -> None:
        text = self.odx_path_var.get().strip()
        if not text:
            messagebox.showinfo("Tester", "Choose an ODX/PDX file first")
            return
        self._apply_odx_file(Path(text))

    def _apply_odx_file(self, path: Path) -> None:
        try:
            database = load_odx(path)
        except Exception as exc:
            messagebox.showerror("Tester", f"ODX load failed: {exc}")
            self._append_log(f"ERROR ODX load failed: {exc}")
            return

        previous_signals = set(self.selected_signals)
        self.odx_database = database
        self.odx_source_path = path
        self.odx_path_var.set(str(path))
        self.signal_definitions = self._signal_definitions_from_odx()
        self.flash_ecus = self._ecus_from_odx()
        self.signal_values = {did: "-" for did in self.signal_definitions}
        self.selected_signals = previous_signals.intersection(self.signal_definitions)
        if not self.selected_signals and self.signal_definitions:
            self.selected_signals.add(next(iter(self.signal_definitions)))

        self._refresh_quick_actions()
        self._refresh_ecu_targets()
        self._refresh_flash_ecu_table()
        self._refresh_signal_list()
        self._refresh_service_builder()
        self._refresh_routine_defaults()
        self._append_log(f"INFO ODX loaded: {path}")

    def _refresh_quick_actions(self) -> None:
        if not hasattr(self, "quick_actions_frame"):
            return
        for child in self.quick_actions_frame.winfo_children():
            child.destroy()
        for index, action in enumerate(self._quick_actions()):
            ttk.Button(self.quick_actions_frame, text=action.label, command=lambda req=action.request: self._send_value(req)).grid(
                row=0,
                column=index,
                padx=(0, 8),
                sticky="ew",
            )
            self.quick_actions_frame.columnconfigure(index, weight=1)

    def _refresh_ecu_targets(self) -> None:
        if not hasattr(self, "ecu_tree"):
            return
        for item in self.ecu_tree.get_children():
            self.ecu_tree.delete(item)
        for address, (name, role, access) in self.flash_ecus.items():
            self.ecu_tree.insert("", "end", text=name, values=(address, role, access))
        first_address = next(iter(self.flash_ecus), "")
        if first_address:
            self.target_var.set(first_address)

    def _refresh_flash_ecu_table(self) -> None:
        if not hasattr(self, "flash_ecu_table"):
            return
        for item in self.flash_ecu_table.get_children():
            self.flash_ecu_table.delete(item)
        for address, (name, role, access) in self.flash_ecus.items():
            self.flash_ecu_table.insert("", "end", iid=address, text=name, values=(address, role, access))
        first_address = next(iter(self.flash_ecus), "")
        if first_address:
            self.flash_ecu_table.selection_set(first_address)
            self.target_var.set(first_address)

    def _refresh_signal_list(self) -> None:
        if not hasattr(self, "signal_list_table"):
            return
        for item in self.signal_list_table.get_children():
            self.signal_list_table.delete(item)
        for did, (name, _) in self.signal_definitions.items():
            self.signal_values.setdefault(did, "-")
            marker = "[x]" if did in self.selected_signals else "[ ]"
            self.signal_list_table.insert("", "end", iid=did, text=marker, values=(did, name))
        self._refresh_signal_results()
        self._render_did_structure_form(next(iter(self.selected_signals), None))

    def _refresh_service_builder(self) -> None:
        if not hasattr(self, "service_combo"):
            return
        services = [service.name for service in self.odx_database.services if any(parameter.is_input for parameter in service.request_parameters)]
        self.service_combo.configure(values=services)
        if services:
            current = self.service_var.get()
            self.service_var.set(current if current in services else services[0])
        else:
            self.service_var.set("")
        self._render_service_fields()

    def _refresh_routine_defaults(self) -> None:
        if not hasattr(self, "routine_var") or not hasattr(self, "routine_type_var"):
            return
        default_routine = self.odx_database.routines[0] if self.odx_database.routines else None
        self.routine_var.set(default_routine.routine_id if default_routine else "FF00")
        self.routine_type_var.set(default_routine.control if default_routine else "01")

    def _build_live_log_panel(self, parent: ttk.Frame) -> None:
        self.live_log_panel = ttk.LabelFrame(parent, text="Live Communication", style="Panel.TLabelframe", padding=10)
        self.live_log_panel.grid(row=1, column=2, sticky="nsew", padx=(0, 14), pady=(14, 8))
        self.live_log_panel.rowconfigure(1, weight=1)
        self.live_log_panel.columnconfigure(0, weight=1)
        self.log_line = tk.StringVar(value="-")
        ttk.Label(self.live_log_panel, textvariable=self.log_line, wraplength=235).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.side_log = tk.Text(
            self.live_log_panel,
            width=28,
            wrap="word",
            state="disabled",
            bg="#FFFFFF",
            relief="solid",
            font=("Consolas", 9),
        )
        self.side_log.grid(row=1, column=0, sticky="nsew")
        ttk.Scrollbar(self.live_log_panel, command=self.side_log.yview).grid(row=1, column=1, sticky="ns")
        self.side_log.configure(yscrollcommand=lambda *args: None)

    def _toggle_live_log(self) -> None:
        if self.show_live_log_var.get():
            self.live_log_panel.grid()
        else:
            self.live_log_panel.grid_remove()

    def _show_page(self, name: str) -> None:
        self.selected_page.set(name)
        self.pages[name].tkraise()

    def _loop_thread(self) -> None:
        if self.loop is None:
            return
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _start_event_loop_thread(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._loop_thread, daemon=True)
        self.thread.start()

    def _run(self, coro) -> None:
        if self.loop is None:
            self.ui_queue.put(("LOG", "ERROR Background event loop is not ready"))
            return
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _connect(self) -> None:
        if self.connected:
            return
        try:
            client = TesterClient(
                tester_address=int(self.source_var.get(), 0),
                target_address=int(self.target_var.get(), 0),
                port=int(self.port_var.get()),
                heartbeat_tx_callback=self._on_heartbeat_tx,
                heartbeat_rx_callback=self._on_heartbeat_rx,
            )
        except ValueError as exc:
            messagebox.showerror("Tester", f"Invalid connection value: {exc}")
            return
        self.client = client
        self.status_var.set("CONNECTING")
        self._run(self._connect_async(client, self.host_var.get()))

    async def _connect_async(self, client: TesterClient, host: str) -> None:
        try:
            await client.connect(host)
            self.connected = True
            self.ui_queue.put(("STATUS", "CONNECTED"))
            self.ui_queue.put(("LOG", f"INFO Connected to {host}:{client.port}"))
            self._run_command(bytes.fromhex("22 F1 90"), purpose="VIN")
            asyncio.create_task(self._watch_disconnect(client))
        except Exception as exc:
            self.connected = False
            self.ui_queue.put(("STATUS", "DISCONNECTED"))
            self.ui_queue.put(("LOG", f"ERROR Connect failed: {exc}"))

    def _on_heartbeat_tx(self, payload: bytes) -> None:
        self.ui_queue.put(("HEARTBEAT_TX", payload))

    def _on_heartbeat_rx(self, payload: bytes) -> None:
        self.ui_queue.put(("HEARTBEAT_RX", payload))

    async def _watch_disconnect(self, client: TesterClient) -> None:
        while self.client is client and not client.disconnected:
            await asyncio.sleep(0.2)
        if self.client is client and self.connected:
            self.connected = False
            self.ui_queue.put(("STATUS", "DISCONNECTED"))
            self.ui_queue.put(("LOG", "INFO Simulator closed the connection; reconnect when ECU reset is complete"))

    def _disconnect(self) -> None:
        if self.client is not None:
            self._run(self._disconnect_async())

    async def _disconnect_async(self) -> None:
        if self.client is not None:
            with contextlib.suppress(Exception):
                await self.client.close()
        self.connected = False
        self.ui_queue.put(("STATUS", "DISCONNECTED"))
        self.ui_queue.put(("LOG", "INFO Disconnected"))

    def _send(self) -> None:
        self._send_value(self.request_var.get())

    def _send_value(self, value: str, purpose: str = "MANUAL") -> None:
        try:
            payload = parse_hex_command(value)
        except ValueError as exc:
            messagebox.showerror("Tester", str(exc))
            return
        if not payload:
            return
        self.request_var.set(value)
        self._run_command(payload, purpose=purpose)

    def _run_command(self, payload: bytes, purpose: str = "MANUAL") -> None:
        if not self.connected or self.client is None:
            messagebox.showwarning("Tester", "Connect to a simulator first")
            return
        self.ui_queue.put(("TX", payload))
        self._run(self._send_async(payload, purpose))

    async def _send_async(self, payload: bytes, purpose: str) -> None:
        if self.client is None:
            return
        started = time.perf_counter()
        try:
            response = await self.client.send_uds(payload)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            self.ui_queue.put(("RX", (payload, response, purpose, elapsed_ms)))
        except Exception as exc:
            if self.client is None or self.client.disconnected:
                self.connected = False
                self.ui_queue.put(("STATUS", "DISCONNECTED"))
            self.ui_queue.put(("LOG", f"ERROR Send failed: {exc}"))

    def _read_dtc(self) -> None:
        mask = self.dtc_mask_var.get().strip() or "FF"
        self._send_value(f"19 02 {mask}", purpose="DTC")

    def _clear_dtc(self) -> None:
        self._send_value("14 FF FF FF", purpose="CLEAR_DTC")

    def _read_selected_snapshot(self) -> None:
        code = self._selected_dtc_code()
        if code:
            self._send_value(f"19 04 {code} 01", purpose="SNAPSHOT")

    def _read_selected_extended(self) -> None:
        code = self._selected_dtc_code()
        if code:
            self._send_value(f"19 06 {code} 01", purpose="EXTENDED")

    def _selected_dtc_code(self) -> str | None:
        selected = self.dtc_table.selection()
        if not selected:
            messagebox.showinfo("Tester", "Select a DTC first")
            return None
        code = self.dtc_table.item(selected[0], "text")
        return code.replace("0x", "")

    def _selected_signal_dids(self) -> list[str]:
        return [did for did in self.signal_definitions if did in self.selected_signals]

    def _toggle_signal_selection(self, _event: tk.Event | None = None) -> None:
        selected = self.signal_list_table.selection()
        if not selected:
            return
        did = selected[0]
        if did in self.selected_signals:
            self.selected_signals.remove(did)
            self.signal_list_table.item(did, text="[ ]")
        else:
            self.selected_signals.add(did)
            self.signal_list_table.item(did, text="[x]")
        self._refresh_signal_results()
        self._render_did_structure_form(did)

    def _refresh_signal_results(self) -> None:
        for item in self.signal_table.get_children():
            self.signal_table.delete(item)
        for did in self._selected_signal_dids():
            self.signal_table.insert("", "end", iid=did, text=did, values=(self.signal_values.get(did, "-"),))

    def _read_selected_signals(self) -> None:
        selected = self._selected_signal_dids()
        if not selected:
            messagebox.showinfo("Tester", "Select at least one signal")
            return
        for did in selected:
            self._send_value(f"22 {did[:2]} {did[2:]}", purpose=f"SIGNAL:{did}")

    def _did_definition(self, did: str):
        normalized = did.upper().replace("0X", "")
        return next((item for item in self.odx_database.dids if item.did == normalized), None)

    def _structure_for_did(self, did: str):
        did_definition = self._did_definition(did)
        if did_definition is None or did_definition.dop_ref is None:
            return None
        return self.odx_database.structures.get(did_definition.dop_ref)

    def _render_did_structure_form(self, did: str | None) -> None:
        if not hasattr(self, "structure_panel"):
            return
        for child in self.structure_panel.winfo_children():
            child.destroy()
        self.structure_field_vars = {}
        self.active_structure_did = did
        structure = self._structure_for_did(did) if did else None
        if did is None or structure is None:
            ttk.Label(self.structure_panel, text="Select a DID backed by STRUCTURE to edit fields.").grid(row=0, column=0, sticky="w")
            return
        ttk.Label(self.structure_panel, text=f"{did}  {structure.name}", style="Muted.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        for row, field in enumerate(structure.fields, start=1):
            variable = tk.StringVar(value="")
            self.structure_field_vars[field.name] = variable
            ttk.Label(self.structure_panel, text=field.name).grid(row=row, column=0, sticky="w", pady=(6, 0), padx=(0, 8))
            ttk.Entry(self.structure_panel, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=(6, 0))
            ttk.Label(self.structure_panel, text=field.dop_ref or "").grid(row=row, column=2, sticky="w", pady=(6, 0), padx=(8, 0))
        buttons = ttk.Frame(self.structure_panel)
        buttons.grid(row=len(structure.fields) + 1, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Build 2E Request", command=self._build_structure_write_request).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Send 2E Request", command=self._send_structure_write_request).pack(side="left")

    def _structure_values(self) -> dict[str, int | float | str | bytes]:
        return {name: self._coerce_input_value(variable.get()) for name, variable in self.structure_field_vars.items()}

    def _build_structure_write_request(self) -> bytes | None:
        if not self.active_structure_did:
            messagebox.showinfo("Tester", "Select a STRUCTURE DID first")
            return None
        try:
            payload = self.odx_database.encode_did_value(self.active_structure_did, self._structure_values())
            if payload is None:
                raise ValueError(f"No encoder for DID {self.active_structure_did}")
            did_bytes = bytes.fromhex(self.active_structure_did)
            request = bytes([0x2E]) + did_bytes + payload
        except Exception as exc:
            messagebox.showerror("Tester", f"Build request failed: {exc}")
            return None
        self.request_var.set(self._hex(request))
        return request

    def _send_structure_write_request(self) -> None:
        request = self._build_structure_write_request()
        if request:
            self._run_command(request, purpose=f"WRITE_DID:{self.active_structure_did}")

    def _render_service_fields(self, _event: tk.Event | None = None) -> None:
        if not hasattr(self, "service_fields_frame"):
            return
        for child in self.service_fields_frame.winfo_children():
            child.destroy()
        self.service_input_vars = {}
        self.service_structure_fields = {}
        service = next((item for item in self.odx_database.services if item.name == self.service_var.get()), None)
        if service is None:
            ttk.Label(self.service_fields_frame, text="No parameterized ODX service available.").grid(row=0, column=0, sticky="w")
            return
        row = 0
        for parameter in service.request_parameters:
            if not parameter.is_input or not parameter.dop_ref:
                continue
            structure = self.odx_database.structures.get(parameter.dop_ref)
            if structure is not None:
                ttk.Label(self.service_fields_frame, text=parameter.name, style="Muted.TLabel").grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
                row += 1
                for field in structure.fields:
                    key = f"{parameter.name}.{field.name}"
                    variable = tk.StringVar(value="")
                    self.service_input_vars[key] = variable
                    self.service_structure_fields[key] = (parameter.name, field.name)
                    ttk.Label(self.service_fields_frame, text=f"  {field.name}").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=(4, 0))
                    ttk.Entry(self.service_fields_frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=(4, 0))
                    row += 1
            else:
                variable = tk.StringVar(value="")
                self.service_input_vars[parameter.name] = variable
                ttk.Label(self.service_fields_frame, text=parameter.name).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=(4, 0))
                ttk.Entry(self.service_fields_frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=(4, 0))
                row += 1

    def _service_values(self) -> dict[str, object]:
        values: dict[str, object] = {}
        for key, variable in self.service_input_vars.items():
            value = self._coerce_input_value(variable.get())
            if key in self.service_structure_fields:
                parameter_name, field_name = self.service_structure_fields[key]
                nested = values.setdefault(parameter_name, {})
                if isinstance(nested, dict):
                    nested[field_name] = value
            else:
                values[key] = value
        return values

    def _build_encoded_service_request(self) -> bytes | None:
        service_name = self.service_var.get()
        if not service_name:
            messagebox.showinfo("Tester", "Select an ODX service first")
            return None
        try:
            request = self.odx_database.encode_service_request(service_name, self._service_values())  # type: ignore[arg-type]
            if request is None:
                raise ValueError(f"Service {service_name} is not available")
        except Exception as exc:
            messagebox.showerror("Tester", f"Build service request failed: {exc}")
            return None
        self.request_var.set(self._hex(request))
        return request

    def _send_encoded_service_request(self) -> None:
        request = self._build_encoded_service_request()
        if request:
            self._run_command(request, purpose=f"SERVICE:{self.service_var.get()}")

    def _coerce_input_value(self, text: str) -> int | float | str | bytes:
        value = text.strip()
        if not value:
            return ""
        if " " in value:
            with contextlib.suppress(ValueError):
                return bytes.fromhex(value.replace("0x", "").replace("0X", ""))
        if value.lower().startswith("0x"):
            with contextlib.suppress(ValueError):
                return int(value, 16)
        with contextlib.suppress(ValueError):
            return int(value)
        with contextlib.suppress(ValueError):
            return float(value)
        return value

    def _execute_routine(self) -> None:
        routine = self.routine_var.get().replace(" ", "")
        if len(routine) != 4:
            messagebox.showerror("Tester", "Routine ID must be 2 bytes")
            return
        self._send_value(f"31 {self.routine_type_var.get()} {routine[:2]} {routine[2:]}", purpose="ROUTINE")

    def _on_flash_ecu_selected(self, _event: tk.Event | None = None) -> None:
        selected = self.flash_ecu_table.selection()
        if selected:
            self.target_var.set(selected[0])

    def _load_flash_file(self) -> None:
        try:
            self._debug_flash("button clicked")
            self._append_log("INFO Flash load: opening file dialog")
            self._debug_flash(f"ensure flash folder begin path={self.flash_directory}")
            self.flash_directory.mkdir(exist_ok=True)
            self._debug_flash("ensure flash folder done")
            self._debug_flash("file dialog begin")
            selected = filedialog.askopenfilename(
                parent=self.root,
                title="Load flash file",
                initialdir=str(self.flash_directory),
                filetypes=(("Binary files", "*.bin"), ("All files", "*.*")),
            )
            self._debug_flash(f"file dialog returned selected={selected!r}")
            if not selected:
                self._append_log("INFO Flash load: cancelled")
                return
            self.flash_status_var.set("Loading flash file...")
            self.root.configure(cursor="watch")
            worker = threading.Thread(
                target=self._load_flash_file_worker,
                args=(Path(selected),),
                daemon=True,
                name="flash-file-loader",
            )
            self._debug_flash("worker start requested")
            worker.start()
            self._append_log("INFO Flash load: reading file metadata")
        except Exception as exc:
            self._debug_flash(f"load failed before worker error={exc!r}")
            messagebox.showerror("Tester", f"Load flash file failed: {exc}")

    def _load_flash_file_worker(self, source: Path) -> None:
        try:
            self._debug_flash(f"worker begin source={source}")
            self._debug_flash("resolve begin")
            source = source.resolve()
            self._debug_flash(f"resolve done source={source}")
            self._debug_flash("stat begin")
            size = source.stat().st_size
            self._debug_flash(f"stat done size={size}")
            self._debug_flash("queue FLASH_FILE_LOADED begin")
            self.ui_queue.put(("FLASH_FILE_LOADED", (source, size)))
            self._debug_flash("queue FLASH_FILE_LOADED done")
        except Exception as exc:
            self._debug_flash(f"worker failed error={exc!r}")
            self.ui_queue.put(("FLASH_FILE_ERROR", str(exc)))

    def _refresh_flash_files(self) -> None:
        try:
            self._debug_flash("refresh list begin")
            self.flash_directory.mkdir(exist_ok=True)
        except OSError as exc:
            self._debug_flash(f"refresh list mkdir failed error={exc!r}")
            self.flash_status_var.set(f"Flash folder unavailable: {exc}")
            return
        for item in self.flash_file_table.get_children():
            self.flash_file_table.delete(item)
        valid_files: list[Path] = []
        selected_still_visible = False
        for path in self.loaded_flash_files:
            size = self.flash_file_sizes.get(path)
            if size is None:
                continue
            valid_files.append(path)
            self.flash_file_table.insert(
                "",
                "end",
                iid=str(path),
                text=path.name,
                values=(self._format_size(size), "-"),
            )
            if self.selected_flash_file == path:
                selected_still_visible = True
        self.loaded_flash_files = valid_files
        if self.selected_flash_file is not None and not selected_still_visible:
            self.selected_flash_file = None
            self.flash_file_info_var.set("No flash file selected")
        self._debug_flash(f"refresh list done count={len(valid_files)}")

    def _on_flash_file_selected(self, _event: tk.Event | None = None) -> None:
        selected = self.flash_file_table.selection()
        self._debug_flash(f"tree selection event selected={selected}")
        if selected:
            self._select_flash_file(Path(selected[0]))

    def _select_flash_file(self, path: Path) -> None:
        self._debug_flash(f"select begin path={path}")
        size = self.flash_file_sizes.get(path)
        if path not in self.loaded_flash_files or size is None:
            self._debug_flash("select unavailable")
            self.flash_file_info_var.set("Selected flash file is unavailable")
            self.selected_flash_file = None
            return
        self.selected_flash_file = path
        self.flash_file_info_var.set(f"{path.name}  ({self._format_size(size)})")
        self._debug_flash(f"select done path={path} size={size}")

    def _start_flash(self) -> None:
        if not self.connected or self.client is None:
            messagebox.showwarning("Tester", "Connect to a simulator first")
            return
        selected_ecu = self.flash_ecu_table.selection()
        if not selected_ecu:
            messagebox.showinfo("Tester", "Select an ECU first")
            return
        if self.selected_flash_file is None or self.selected_flash_file not in self.loaded_flash_files:
            messagebox.showinfo("Tester", "Select a flash file first")
            return
        target_address = int(selected_ecu[0], 0)
        self.flash_progress.configure(value=0)
        self.flash_status_var.set("Flashing...")
        self._run(self._flash_async(target_address, self.selected_flash_file))

    async def _flash_async(self, target_address: int, flash_file: Path) -> None:
        if self.client is None:
            return
        try:
            data = flash_file.read_bytes()
            if not data:
                raise RuntimeError("Flash file is empty")
            block_size = max(self.flash_block_size, 1)
            total_blocks = (len(data) + block_size - 1) // block_size
            total_steps = 7 + total_blocks
            completed = 0

            async def step(label: str, request: bytes) -> bytes:
                nonlocal completed
                self.ui_queue.put(("FLASH_STATUS", label))
                self.ui_queue.put(("TX", request))
                response = await self.client.send_uds(request, target_address=target_address)
                self.ui_queue.put(("RX", (request, response, "FLASH", 0)))
                if response.startswith(b"\x7F"):
                    raise RuntimeError(f"{label} failed: {response.hex(' ').upper()}")
                completed += 1
                self.ui_queue.put(("FLASH_PROGRESS", int(completed * 100 / total_steps)))
                return response

            await step("Entering programming session", bytes.fromhex("10 03"))
            await step("Requesting seed", bytes.fromhex("27 01"))
            await step("Sending key", bytes.fromhex("27 02 87 65 43 21"))
            await step("Running pre-programming routine", bytes.fromhex("31 01 FF 00"))
            await step("Requesting download", self._request_download_payload(len(data)))
            for index in range(total_blocks):
                block_counter = (index + 1) & 0xFF
                chunk = data[index * block_size : (index + 1) * block_size]
                await step(f"Transferring block {index + 1}/{total_blocks}", bytes([0x36, block_counter]) + chunk)
            await step("Exiting transfer", bytes.fromhex("37"))
            await step("Running post-programming routine", bytes.fromhex("31 01 FF 01"))
            self.ui_queue.put(("FLASH_PROGRESS", 100))
            self.ui_queue.put(("FLASH_STATUS", "Flash completed"))
        except Exception as exc:
            self.ui_queue.put(("FLASH_STATUS", f"Flash failed: {exc}"))

    def _request_download_payload(self, size: int) -> bytes:
        return (
            bytes.fromhex("34 00 44")
            + self.flash_start_address.to_bytes(4, "big")
            + size.to_bytes(4, "big")
        )

    def _format_size(self, size: int) -> str:
        if size < 1024:
            return f"{size} B"
        return f"{size / 1024:.1f} KB"

    def _poll_ui(self) -> None:
        while True:
            try:
                event, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if event == "STATUS":
                self._apply_status(str(payload))
            elif event == "TX":
                self._append_log("Request " + self._hex(payload))
            elif event == "RX":
                request, response, purpose, elapsed_ms = payload  # type: ignore[misc]
                self._handle_response(request, response, str(purpose), int(elapsed_ms))
            elif event == "HEARTBEAT_TX":
                if self.show_heartbeat_var.get():
                    self._append_log("Request " + self._hex(payload))
            elif event == "HEARTBEAT_RX":
                if self.show_heartbeat_var.get():
                    self._append_log("Response " + self._hex(payload))
            elif event == "LOG":
                self._append_log(str(payload))
            elif event == "FLASH_STATUS":
                self.flash_status_var.set(str(payload))
                self._append_log("INFO " + str(payload))
            elif event == "FLASH_PROGRESS":
                self.flash_progress.configure(value=int(payload))
            elif event == "FLASH_FILE_LOADED":
                self._debug_flash(f"ui event FLASH_FILE_LOADED payload={payload}")
                path, size = payload  # type: ignore[misc]
                flash_path = Path(path)
                self.flash_file_sizes[flash_path] = int(size)
                if flash_path not in self.loaded_flash_files:
                    self.loaded_flash_files.append(flash_path)
                self._refresh_flash_files()
                self._select_flash_file(flash_path)
                self.flash_status_var.set("Flash file loaded")
                self.root.configure(cursor="")
                self._append_log(f"INFO Flash load: loaded {flash_path.name}")
                self._debug_flash("ui event FLASH_FILE_LOADED done")
            elif event == "FLASH_FILE_ERROR":
                self._debug_flash(f"ui event FLASH_FILE_ERROR payload={payload}")
                self.flash_status_var.set("Flash file load failed")
                self.root.configure(cursor="")
                messagebox.showerror("Tester", f"Load flash file failed: {payload}")
        self.root.after(100, self._poll_ui)

    def _apply_status(self, status: str) -> None:
        self.status_var.set(status)
        is_connected = status == "CONNECTED"
        self.connect_button.configure(state="disabled" if is_connected else "normal")
        self.disconnect_button.configure(state="normal" if is_connected else "disabled")
        if not is_connected:
            self.session_var.set("Default")
            self.security_var.set("Locked")

    def _handle_response(self, request: bytes, response: bytes, purpose: str, elapsed_ms: int) -> None:
        negative = decode_negative_response(response)
        if negative is not None:
            service_id, nrc, description = negative
            detail = f"{self._hex(response)}  NRC 0x{nrc:02X} {description} for SID 0x{service_id:02X}"
            self.last_response_var.set(detail)
            self._append_log(f"Negative Response {detail}  [{elapsed_ms} ms]")
        else:
            self.last_response_var.set(self._hex(response))
            self._append_log(f"Response {self._hex(response)}  [{elapsed_ms} ms]")
        self._update_state_from_response(request, response)
        if purpose == "VIN":
            self._update_vin(response)
        elif purpose == "DTC":
            self._update_dtc_table(response)
        elif purpose == "CLEAR_DTC":
            self._run_command(bytes.fromhex("19 02 FF"), purpose="DTC")
        elif purpose.startswith("SIGNAL:"):
            self._update_signal_detail(purpose[7:], response)
        elif purpose in {"ROUTINE", "SNAPSHOT", "EXTENDED"}:
            append_text(self.routine_log, f"{purpose}  {self._hex(response)}")

    def _update_state_from_response(self, request: bytes, response: bytes) -> None:
        if len(response) >= 2 and response[0] == 0x50:
            self.session_var.set(f"0x{response[1]:02X}")
        if len(response) >= 2 and response[0] in {0x67, 0x69}:
            self.security_var.set("Unlocked")
        if len(response) >= 3 and response[:2] == b"\x7F\x27":
            self.security_var.set("Locked")

    def _update_vin(self, response: bytes) -> None:
        if len(response) > 3 and response[:3] == bytes.fromhex("62 F1 90"):
            vin = response[3:].decode("ascii", errors="ignore").strip()
            self.vin_var.set(vin or "-")

    def _update_dtc_table(self, response: bytes) -> None:
        if len(response) < 3 or response[0] != 0x59 or response[1] != 0x02:
            return
        for item in self.dtc_table.get_children():
            self.dtc_table.delete(item)
        self.dtc_rows.clear()
        data = response[3:]
        for offset in range(0, len(data), 4):
            chunk = data[offset : offset + 4]
            if len(chunk) != 4:
                continue
            code = chunk[:3].hex(" ").upper()
            status = f"0x{chunk[3]:02X}"
            description = self._dtc_status_text(chunk[3])
            item = self.dtc_table.insert("", "end", text=f"0x{code.replace(' ', '')}", values=(status, "-", "primary", description))
            self.dtc_rows[item] = (code, status, "-", description)

    def _update_signal_detail(self, did: str, response: bytes) -> None:
        if len(response) < 3 or response[0] != 0x62:
            return
        value = self.odx_database.decode_did_response(did, response) or response[3:].hex(" ").upper()
        self.signal_values[did] = value
        if did not in self.selected_signals:
            self.selected_signals.add(did)
            if self.signal_list_table.exists(did):
                self.signal_list_table.item(did, text="[x]")
        self._refresh_signal_results()

    def _dtc_status_text(self, status: int) -> str:
        parts = []
        if status & 0x01:
            parts.append("testFailed")
        if status & 0x08:
            parts.append("confirmed")
        if status & 0x20:
            parts.append("warningIndicator")
        if not parts:
            parts.append("inactive")
        return ", ".join(parts)

    def _append_log(self, line: str) -> None:
        timestamped = f"{time.strftime('%H:%M:%S')}  {line}"
        self.log_line.set(line)
        append_text(self.side_log, timestamped)

    def _hex(self, payload: object) -> str:
        if isinstance(payload, bytes):
            return payload.hex(" ").upper()
        return str(payload)

    def _on_close(self) -> None:
        if self.client is not None:
            if self.loop is not None:
                future = asyncio.run_coroutine_threadsafe(self.client.close(), self.loop)
                with contextlib.suppress(Exception):
                    future.result(timeout=1)
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    TesterGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
