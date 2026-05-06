import logging
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import BOTH, END, HORIZONTAL, LEFT, RIGHT, VERTICAL, X, Y, filedialog, messagebox, simpledialog, ttk
import tkinter as tk
from xml.etree import ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from odx import validate_database
from odx.loader import load_odx_root
from odx.package import open_pdx, save_pdx
from odx.xml_tools import parse_xml, pretty_xml, validate_xml

APP_NAME = "ODX Editor"
DEFAULT_ODX = """<?xml version="1.0" encoding="UTF-8"?>
<ODX>
  <DIAG-LAYER SHORT-NAME="New ECU" LOGICAL-ADDRESS="0x0001" ROLE="ecu" ACCESS="direct">
    <DIAG-SERVICE ID="SERVICE.NEW" SHORT-NAME="New Service" SEMANTIC="CUSTOM">
      <REQUEST-REF ID-REF="REQ.NEW" />
      <POS-RESPONSE>62 00</POS-RESPONSE>
    </DIAG-SERVICE>
  </DIAG-LAYER>
  <REQUEST ID="REQ.NEW" SHORT-NAME="REQ.NEW">
    <BYTES>22 00</BYTES>
  </REQUEST>
</ODX>
"""


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class TextLogHandler(logging.Handler):
    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.text_widget.after(0, self._append, msg)

    def _append(self, msg: str) -> None:
        self.text_widget.configure(state="normal")
        self.text_widget.insert(END, msg + "\n")
        self.text_widget.see(END)
        self.text_widget.configure(state="disabled")


class OdxEditorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1440x860")
        self.root.minsize(1180, 720)

        self.current_path: Path | None = None
        self.current_type = "ODX"
        self.xml_entry_name = "database.odx"
        self.pdx_entries: dict[str, bytes] = {}
        self.tree_paths: dict[str, ET.Element] = {}
        self.domain_items: dict[str, tuple[str, str]] = {}
        self.selected_element: ET.Element | None = None
        self.xml_root: ET.Element | None = None
        self.dirty = False
        self._updating_source = False
        self.source_dirty = False

        self._build_ui()
        self._setup_logging()
        self._bind_events()
        self.new_odx()

    def _build_ui(self) -> None:
        self.style = ttk.Style()
        self.style.configure("Primary.TButton", padding=(12, 7))
        self.style.configure("Tool.TButton", padding=(10, 6))

        toolbar = ttk.Frame(self.root, padding=(10, 8))
        toolbar.pack(fill=X)

        ttk.Button(toolbar, text="新建 ODX", style="Primary.TButton", command=self.new_odx).pack(side=LEFT, padx=(0, 8))
        ttk.Button(toolbar, text="加载 ODX/PDX", style="Primary.TButton", command=self.load_file).pack(side=LEFT, padx=(0, 8))
        ttk.Button(toolbar, text="保存 ODX", style="Tool.TButton", command=self.save_odx).pack(side=LEFT, padx=(0, 8))
        ttk.Button(toolbar, text="另存为 ODX", style="Tool.TButton", command=self.save_as_odx).pack(side=LEFT, padx=(0, 8))
        ttk.Button(toolbar, text="导出 PDX", style="Tool.TButton", command=self.export_pdx).pack(side=LEFT, padx=(0, 8))
        ttk.Button(toolbar, text="格式化 XML", style="Tool.TButton", command=self.format_source).pack(side=LEFT, padx=(0, 8))
        ttk.Button(toolbar, text="检查 XML", style="Tool.TButton", command=self.validate_source).pack(side=LEFT)

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(toolbar, textvariable=self.status_var, anchor="e").pack(side=RIGHT, fill=X, expand=True)

        self.main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main = self.main_pane
        main.pack(fill=BOTH, expand=True, padx=10, pady=(0, 8))

        left = ttk.Frame(main)
        main.add(left, weight=1)
        self.right_pane = ttk.PanedWindow(main, orient=tk.VERTICAL)
        right = self.right_pane
        main.add(right, weight=3)

        meta = ttk.LabelFrame(left, text="工程信息", padding=8)
        meta.pack(fill=X, pady=(0, 8))
        self.file_var = tk.StringVar(value="未加载")
        self.type_var = tk.StringVar(value="-")
        self.dirty_var = tk.StringVar(value="未修改")
        ttk.Label(meta, text="文件").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(meta, textvariable=self.file_var).grid(row=0, column=1, sticky="ew")
        ttk.Label(meta, text="类型").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Label(meta, textvariable=self.type_var).grid(row=1, column=1, sticky="ew")
        ttk.Label(meta, text="状态").grid(row=2, column=0, sticky="w", padx=(0, 8))
        ttk.Label(meta, textvariable=self.dirty_var).grid(row=2, column=1, sticky="ew")
        meta.columnconfigure(1, weight=1)

        stats = ttk.LabelFrame(left, text="ODX 概览", padding=8)
        stats.pack(fill=X, pady=(0, 8))
        self.stats_var = tk.StringVar(value="诊断层 0 | 服务 0 | 请求 0 | DOP 0")
        ttk.Label(stats, textvariable=self.stats_var).pack(anchor="w")

        tree_frame = ttk.LabelFrame(left, text="XML 结构", padding=6)
        tree_frame.pack(fill=BOTH, expand=True)
        left_tabs = ttk.Notebook(tree_frame)
        left_tabs.pack(fill=BOTH, expand=True)
        xml_tab = ttk.Frame(left_tabs)
        domain_tab = ttk.Frame(left_tabs)
        left_tabs.add(xml_tab, text="XML")
        left_tabs.add(domain_tab, text="Domain")

        self.tree = ttk.Treeview(xml_tab, show="tree")
        tree_scroll = ttk.Scrollbar(xml_tab, orient=VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        tree_scroll.pack(side=RIGHT, fill=Y)

        domain_tab.rowconfigure(0, weight=2)
        domain_tab.rowconfigure(1, weight=1)
        domain_tab.columnconfigure(0, weight=1)
        self.domain_tree = ttk.Treeview(domain_tab, show="tree")
        self.domain_tree.grid(row=0, column=0, sticky="nsew")
        domain_scroll = ttk.Scrollbar(domain_tab, orient=VERTICAL, command=self.domain_tree.yview)
        domain_scroll.grid(row=0, column=1, sticky="ns")
        self.domain_tree.configure(yscrollcommand=domain_scroll.set)
        self.domain_detail = tk.Text(domain_tab, height=8, wrap="word", state="disabled", font=("Consolas", 9))
        self.domain_detail.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(8, 0))

        self.upper_pane = ttk.PanedWindow(right, orient=tk.HORIZONTAL)
        upper = self.upper_pane
        right.add(upper, weight=4)

        editor_frame = ttk.LabelFrame(upper, text="可视化编辑", padding=8)
        upper.add(editor_frame, weight=1)
        self.attr_frame = ttk.Frame(editor_frame)
        self.attr_frame.pack(fill=BOTH, expand=True)
        attr_buttons = ttk.Frame(editor_frame)
        attr_buttons.pack(fill=X, pady=(8, 0))
        ttk.Button(attr_buttons, text="添加属性", command=self.add_attribute).pack(side=LEFT, padx=(0, 8))
        ttk.Button(attr_buttons, text="应用属性修改", command=self.apply_attributes).pack(side=LEFT, padx=(0, 8))
        ttk.Button(attr_buttons, text="新建同级节点", command=self.add_sibling_node).pack(side=LEFT, padx=(0, 8))
        ttk.Button(attr_buttons, text="新建子节点", command=self.add_child_node).pack(side=LEFT, padx=(0, 8))
        ttk.Button(attr_buttons, text="删除选中节点", command=self.delete_selected_node).pack(side=LEFT)

        source_frame = ttk.LabelFrame(upper, text="XML 源码", padding=6)
        upper.add(source_frame, weight=2)
        self.source = tk.Text(source_frame, wrap="none", undo=True, font=("Consolas", 10))
        source_y = ttk.Scrollbar(source_frame, orient=VERTICAL, command=self.source.yview)
        source_x = ttk.Scrollbar(source_frame, orient=HORIZONTAL, command=self.source.xview)
        self.source.configure(yscrollcommand=source_y.set, xscrollcommand=source_x.set)
        self.source.grid(row=0, column=0, sticky="nsew")
        source_y.grid(row=0, column=1, sticky="ns")
        source_x.grid(row=1, column=0, sticky="ew")
        source_frame.rowconfigure(0, weight=1)
        source_frame.columnconfigure(0, weight=1)
        self.source.tag_configure("selected_node", background="#FFF3A3", foreground="#1B1B1B")

        log_frame = ttk.LabelFrame(right, text="运行日志", padding=6)
        right.add(log_frame, weight=1)
        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="word", font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=True)
        self.tree_menu = tk.Menu(self.root, tearoff=False)
        self.tree_menu.add_command(label="新建子节点", command=self.add_child_node)
        self.tree_menu.add_command(label="新建同级节点", command=self.add_sibling_node)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="删除选中节点", command=self.delete_selected_node)
        self.root.after(120, self._set_initial_panes)

    def _setup_logging(self) -> None:
        log_dir = app_root() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / "odx_editor.log"
        self.logger = logging.getLogger("odx_editor")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        file_handler = logging.FileHandler(self.log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        text_handler = TextLogHandler(self.log_text)
        text_handler.setFormatter(formatter)
        text_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(text_handler)
        self.logger.info("ODX Editor 启动，日志文件：%s", self.log_path)

    def _bind_events(self) -> None:
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Button-3>", self.on_tree_right_click)
        self.domain_tree.bind("<<TreeviewSelect>>", self.on_domain_select)
        self.source.bind("<<Modified>>", self.on_source_modified)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _set_initial_panes(self) -> None:
        try:
            self.root.update_idletasks()
            self.main_pane.sashpos(0, 330)
            self.upper_pane.sashpos(0, 430)
            self.right_pane.sashpos(0, 610)
        except tk.TclError:
            self.logger.debug("初始化窗格比例失败", exc_info=True)

    def guarded(self, action_name: str, func, *args, **kwargs):
        self.logger.info("开始：%s", action_name)
        try:
            result = func(*args, **kwargs)
            self.logger.info("完成：%s", action_name)
            return result
        except Exception as exc:
            self.logger.error("%s 失败：%s", action_name, exc)
            self.logger.debug(traceback.format_exc())
            messagebox.showerror(APP_NAME, f"{action_name}失败：\n{exc}\n\n详情见日志：{self.log_path}")
            return None

    def new_odx(self) -> None:
        self.guarded("新建 ODX", self._new_odx)

    def _new_odx(self) -> None:
        if not self.confirm_discard_changes():
            self.logger.info("用户取消新建，保留当前修改")
            return
        self.current_path = None
        self.current_type = "ODX"
        self.xml_entry_name = "database.odx"
        self.pdx_entries = {}
        self.load_xml_text(DEFAULT_ODX)
        self.set_dirty(False)
        self.status_var.set("已新建 ODX")

    def load_file(self) -> None:
        self.guarded("加载文件", self._load_file)

    def _load_file(self) -> None:
        if not self.confirm_discard_changes():
            self.logger.info("用户取消加载，保留当前修改")
            return
        path_text = filedialog.askopenfilename(
            title="选择 ODX/PDX 文件",
            filetypes=[("ODX / PDX", "*.odx *.xml *.pdx"), ("ODX", "*.odx"), ("PDX", "*.pdx"), ("XML", "*.xml"), ("All files", "*.*")],
        )
        self.logger.info("文件选择结果：%s", path_text or "<empty>")
        if not path_text:
            return

        path = Path(path_text)
        suffix = path.suffix.lower()
        if suffix == ".pdx":
            self._load_pdx(path)
        else:
            text = path.read_text(encoding="utf-8-sig")
            self.current_path = path
            self.current_type = "ODX"
            self.xml_entry_name = path.name
            self.pdx_entries = {}
            self.load_xml_text(text)
            self.set_dirty(False)
            self.status_var.set(f"已加载 {path.name}")

    def _load_pdx(self, path: Path) -> None:
        self.logger.info("读取 PDX：%s", path)
        package = open_pdx(path)
        entries = package.entries
        xml_names = [name for name in entries if name.lower().endswith((".odx", ".xml"))]
        for name, data in entries.items():
            self.logger.debug("PDX 条目：%s bytes=%s", name, len(data))
        self.logger.info("PDX XML 候选：%s", ", ".join(xml_names) or "<none>")
        if not xml_names:
            raise ValueError("PDX 中没有找到 .odx 或 .xml 文件")
        selected = package.active_entry
        if len(xml_names) > 1:
            choice = simpledialog.askstring(APP_NAME, "PDX 中有多个 XML/ODX 条目，请输入要打开的条目名称：", initialvalue=selected)
            if choice:
                selected = choice
        text = entries[selected].decode("utf-8-sig")
        self.current_path = path
        self.current_type = "PDX"
        self.xml_entry_name = selected
        self.pdx_entries = entries
        self.load_xml_text(text)
        self.set_dirty(False)
        self.status_var.set(f"已加载 {path.name} / {selected}")

    def load_xml_text(self, text: str) -> None:
        self.xml_root = parse_xml(text)
        self.selected_element = None
        self.refresh_source()
        self.refresh_tree()
        self.refresh_domain_view()
        self.refresh_stats()
        self.clear_attribute_editor("从左侧选择 XML 节点进行编辑")
        self.refresh_meta()

    def refresh_source(self) -> None:
        if self.xml_root is None:
            return
        self._updating_source = True
        self.clear_source_highlight()
        self.source.delete("1.0", END)
        text, selected_range = self.pretty_xml_with_selected_range()
        self.source.insert("1.0", text)
        self.source.edit_modified(False)
        self.source_dirty = False
        self._updating_source = False
        self.highlight_selected_source(selected_range)

    def refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.tree_paths.clear()
        if self.xml_root is None:
            return
        self._insert_tree_node("", self.xml_root)

    def _insert_tree_node(self, parent_id: str, element: ET.Element) -> None:
        item_id = f"i{len(self.tree_paths)}"
        label = self.node_label(element)
        self.tree.insert(parent_id, END, iid=item_id, text=label, open=parent_id == "")
        self.tree_paths[item_id] = element
        for child in list(element):
            self._insert_tree_node(item_id, child)

    def node_label(self, element: ET.Element) -> str:
        short_name = element.attrib.get("SHORT-NAME")
        identifier = element.attrib.get("ID")
        suffix = short_name or identifier or (element.text or "").strip()[:28]
        return f"{element.tag}  {suffix}" if suffix else element.tag

    def refresh_domain_view(self) -> None:
        self.domain_tree.delete(*self.domain_tree.get_children())
        self.domain_items.clear()
        self.set_domain_detail("")
        if self.xml_root is None:
            return
        try:
            database = load_odx_root(parse_xml(self.source.get("1.0", END).strip() or self.pretty_xml()))
        except Exception as exc:
            root = self.domain_tree.insert("", END, text=f"Domain parse failed: {exc}", open=True)
            self.domain_items[root] = ("error", str(exc))
            return

        categories = {
            "ECU": [(ecu.name, ecu.address) for ecu in database.ecus],
            "Service": [(service.name, service.semantic) for service in database.services],
            "DID": [(f"{did.did}  {did.name}", did.did) for did in database.dids],
            "DOP": [(name, name) for name in database.dops],
            "Structure": [(name, name) for name in database.structures],
            "NRC": [
                (f"{service.name}: 0x{nrc:02X}", f"{service.name}|{nrc}")
                for service in database.services
                for response in service.negative_responses
                for nrc in response.nrcs
            ],
        }
        for category, rows in categories.items():
            parent = self.domain_tree.insert("", END, text=f"{category} ({len(rows)})", open=category in {"DID", "Service"})
            self.domain_items[parent] = ("category", category)
            for label, key in rows:
                item_id = self.domain_tree.insert(parent, END, text=label)
                self.domain_items[item_id] = (category.lower(), key)
        issues = validate_database(database)
        if issues:
            parent = self.domain_tree.insert("", END, text=f"Validation ({len(issues)})", open=False)
            self.domain_items[parent] = ("category", "validation")
            for issue in issues:
                item_id = self.domain_tree.insert(parent, END, text=f"{issue.severity}: {issue.code}")
                self.domain_items[item_id] = ("validation", issue.message)

    def on_domain_select(self, _event=None) -> None:
        selection = self.domain_tree.selection()
        if not selection:
            return
        kind, key = self.domain_items.get(selection[0], ("", ""))
        try:
            database = load_odx_root(parse_xml(self.source.get("1.0", END).strip() or self.pretty_xml()))
        except Exception as exc:
            self.set_domain_detail(str(exc))
            return
        lines: list[str] = []
        if kind == "did":
            did = next((item for item in database.dids if item.did == key), None)
            if did:
                lines.extend([f"DID: {did.did}", f"Name: {did.name}", f"Description: {did.description or '-'}"])
                lines.extend(self.did_reference_chain(database, did.did))
        elif kind == "service":
            service = next((item for item in database.services if item.name == key), None)
            if service:
                lines.extend([f"Service: {service.name}", f"Semantic: {service.semantic or '-'}", f"Request: {service.request.hex(' ').upper() or '-'}"])
                if service.positive_response:
                    lines.append(f"Positive response: {service.positive_response.payload_prefix.hex(' ').upper() or '-'}")
                if service.negative_responses:
                    nrcs = sorted({nrc for response in service.negative_responses for nrc in response.nrcs})
                    lines.append("Allowed NRC: " + ", ".join(f"0x{nrc:02X}" for nrc in nrcs))
        elif kind == "dop":
            dop = database.dops.get(key)
            if dop:
                lines.extend([f"DOP: {dop.name}", f"Base type: {dop.base_data_type}", f"Byte length: {dop.byte_length or '-'}", f"COMPU-METHOD: {dop.compu_method_ref or '-'}"])
        elif kind == "structure":
            structure = database.structures.get(key)
            if structure:
                lines.append(f"Structure: {structure.name}")
                for field in structure.fields:
                    lines.append(f"- {field.name}: {field.dop_ref or '-'} @ {field.byte_position if field.byte_position is not None else 'auto'}")
        elif kind == "validation":
            lines.append(key)
        else:
            lines.append(key)
        self.set_domain_detail("\n".join(lines))

    def did_reference_chain(self, database, did_value: str) -> list[str]:
        did = next((item for item in database.dids if item.did == did_value), None)
        if did is None or not did.dop_ref:
            return ["Reference: -"]
        lines = [f"Reference: DID {did.did} -> {did.dop_ref}"]
        structure = database.structures.get(did.dop_ref)
        if structure is not None:
            for field in structure.fields:
                dop = database.dops.get(field.dop_ref or "")
                compu = database.computations.get(dop.compu_method_ref or "") if dop else None
                unit = compu.unit_ref or compu.unit if compu else ""
                lines.append(f"  {field.name} -> {field.dop_ref or '-'} -> {dop.compu_method_ref if dop and dop.compu_method_ref else '-'} -> {unit or '-'}")
            return lines
        dop = database.dops.get(did.dop_ref)
        compu = database.computations.get(dop.compu_method_ref or "") if dop else None
        unit = compu.unit_ref or compu.unit if compu else ""
        lines.append(f"DOP -> COMPU -> UNIT: {did.dop_ref} -> {dop.compu_method_ref if dop and dop.compu_method_ref else '-'} -> {unit or '-'}")
        return lines

    def set_domain_detail(self, text: str) -> None:
        self.domain_detail.configure(state="normal")
        self.domain_detail.delete("1.0", END)
        if text:
            self.domain_detail.insert("1.0", text)
        self.domain_detail.configure(state="disabled")

    def refresh_stats(self) -> None:
        if self.xml_root is None:
            self.stats_var.set("诊断层 0 | 服务 0 | 请求 0 | DOP 0")
            return
        counts = {
            "诊断层": len(self.xml_root.findall(".//DIAG-LAYER")),
            "服务": len(self.xml_root.findall(".//DIAG-SERVICE")),
            "请求": len(self.xml_root.findall(".//REQUEST")),
            "DOP": len(self.xml_root.findall(".//DATA-OBJECT-PROP")),
        }
        self.stats_var.set(" | ".join(f"{name} {value}" for name, value in counts.items()))

    def refresh_meta(self) -> None:
        self.file_var.set(str(self.current_path) if self.current_path else "新建文档")
        self.type_var.set(self.current_type)
        self.dirty_var.set("已修改" if self.dirty else "未修改")

    def on_tree_select(self, _event=None) -> None:
        self.guarded("选择节点", self._on_tree_select)

    def _on_tree_select(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        item_id = selection[0]
        self.selected_element = self.tree_paths.get(item_id)
        label = self.node_label(self.selected_element) if self.selected_element is not None else "<none>"
        self.logger.debug("选中节点：%s", label)
        self.render_attribute_editor()
        self.highlight_selected_source()

    def on_tree_right_click(self, event: tk.Event) -> None:
        item_id = self.tree.identify_row(event.y)
        if item_id:
            self.tree.selection_set(item_id)
            self.tree.focus(item_id)
            self.selected_element = self.tree_paths.get(item_id)
            self.render_attribute_editor()
            self.highlight_selected_source()
        self.tree_menu.tk_popup(event.x_root, event.y_root)

    def clear_source_highlight(self) -> None:
        self.source.tag_remove("selected_node", "1.0", END)

    def highlight_selected_source(self, selected_range: tuple[int, int] | None = None) -> None:
        self.clear_source_highlight()
        if self.selected_element is None:
            return
        if selected_range is None and not self.source_dirty:
            _, selected_range = self.pretty_xml_with_selected_range()
        if selected_range is None:
            return
        start_offset, end_offset = selected_range
        start_index = f"1.0+{start_offset}c"
        end_index = f"1.0+{end_offset}c"
        self.source.tag_add("selected_node", start_index, end_index)
        self.source.see(start_index)

    def pretty_xml_with_selected_range(self) -> tuple[str, tuple[int, int] | None]:
        if self.xml_root is None:
            return "", None
        marker_name = "__ODX_EDITOR_SELECTED__"
        marker_value = "1"
        selected_range = None
        if self.selected_element is None:
            return self.pretty_xml(), None
        original_value = self.selected_element.attrib.get(marker_name)
        had_original = marker_name in self.selected_element.attrib
        self.selected_element.attrib[marker_name] = marker_value
        try:
            marked_text = pretty_xml(self.xml_root)
        finally:
            if had_original:
                self.selected_element.attrib[marker_name] = original_value or ""
            else:
                self.selected_element.attrib.pop(marker_name, None)

        marker_match = re.search(rf'\s{re.escape(marker_name)}="{re.escape(marker_value)}"', marked_text)
        if marker_match is None:
            return self.pretty_xml(), None
        opening_start = marked_text.rfind("<", 0, marker_match.start())
        if opening_start < 0:
            return self.pretty_xml(), None
        opening_end = marked_text.find(">", opening_start)
        if opening_end < 0:
            return self.pretty_xml(), None
        raw_range = self.element_range_in_marked_text(marked_text, opening_start, opening_end)
        clean_text = marked_text[: marker_match.start()] + marked_text[marker_match.end() :]
        if raw_range is not None:
            start, end = raw_range
            marker_length = marker_match.end() - marker_match.start()
            clean_start = start
            clean_end = end - marker_length if marker_match.start() < end else end
            selected_range = (clean_start, clean_end)
        return clean_text, selected_range

    def element_range_in_marked_text(self, text: str, opening_start: int, opening_end: int) -> tuple[int, int] | None:
        tag_match = re.match(r"<([^\s>/]+)", text[opening_start:opening_end + 1])
        if tag_match is None:
            return None
        tag = tag_match.group(1)
        if text[max(opening_start, opening_end - 1) : opening_end + 1] == "/>":
            return opening_start, opening_end + 1
        token_pattern = re.compile(rf"</?{re.escape(tag)}(?=[\s>/])")
        depth = 0
        for match in token_pattern.finditer(text, opening_start):
            token_start = match.start()
            token_end = text.find(">", token_start)
            if token_end < 0:
                return None
            is_close = text[token_start + 1 : token_start + 2] == "/"
            is_self_close = text[max(token_start, token_end - 1) : token_end + 1] == "/>"
            if not is_close:
                depth += 1
                if is_self_close:
                    depth -= 1
            else:
                depth -= 1
            if depth == 0:
                return opening_start, token_end + 1
        return None

    def render_attribute_editor(self) -> None:
        if self.selected_element is None:
            self.clear_attribute_editor("从左侧选择 XML 节点进行编辑")
            return

        for child in self.attr_frame.winfo_children():
            child.destroy()

        ttk.Label(self.attr_frame, text="节点名称", font=("", 10, "bold")).pack(anchor="w", pady=(0, 4))
        self.tag_var = tk.StringVar(value=self.selected_element.tag)
        self.tag_entry = ttk.Entry(self.attr_frame, textvariable=self.tag_var)
        self.tag_entry.pack(fill=X, pady=(0, 8))

        ttk.Label(self.attr_frame, text="属性").pack(anchor="w", pady=(0, 4))
        self.attr_rows: list[tuple[tk.StringVar, tk.StringVar]] = []
        for key, value in self.selected_element.attrib.items():
            self._add_attr_row(key, value)
        if not self.selected_element.attrib:
            self._add_attr_row("", "")

        ttk.Label(self.attr_frame, text="文本内容").pack(anchor="w", pady=(10, 4))
        self.text_value = tk.Text(self.attr_frame, height=5, wrap="word")
        self.text_value.pack(fill=X)
        self.text_value.insert("1.0", (self.selected_element.text or "").strip())

    def clear_attribute_editor(self, message: str) -> None:
        for child in self.attr_frame.winfo_children():
            child.destroy()
        ttk.Label(self.attr_frame, text=message).pack(anchor="w")

    def _add_attr_row(self, key: str = "", value: str = "") -> None:
        row = ttk.Frame(self.attr_frame)
        row.pack(fill=X, pady=3)
        key_var = tk.StringVar(value=key)
        value_var = tk.StringVar(value=value)
        ttk.Entry(row, textvariable=key_var, width=22).pack(side=LEFT, padx=(0, 6))
        ttk.Entry(row, textvariable=value_var).pack(side=LEFT, fill=X, expand=True, padx=(0, 6))
        ttk.Button(row, text="删除", command=lambda r=row, pair=(key_var, value_var): self.remove_attr_row(r, pair)).pack(side=LEFT)
        self.attr_rows.append((key_var, value_var))

    def add_attribute(self) -> None:
        self.guarded("添加属性", self._add_attribute)

    def _add_attribute(self) -> None:
        if self.selected_element is None:
            raise ValueError("请先选择一个 XML 节点")
        self._add_attr_row("", "")

    def add_child_node(self) -> None:
        self.guarded("新建子节点", self._add_child_node)

    def _add_child_node(self) -> None:
        if self.selected_element is None:
            raise ValueError("请先选择一个 XML 节点")
        child = self._create_blank_node(self.default_child_tag(self.selected_element))
        self.selected_element.append(child)
        self._after_node_structure_change(child, "已新建子节点，请在中间编辑区填写节点名称、属性或文本")

    def add_sibling_node(self) -> None:
        self.guarded("新建同级节点", self._add_sibling_node)

    def _add_sibling_node(self) -> None:
        if self.xml_root is None or self.selected_element is None:
            raise ValueError("请先选择一个 XML 节点")
        if self.selected_element is self.xml_root:
            raise ValueError("根节点没有同级节点，请在根节点下新建子节点")
        parent = self.find_parent(self.xml_root, self.selected_element)
        if parent is None:
            raise ValueError("没有找到父节点")
        sibling = self._create_blank_node(self.selected_element.tag)
        children = list(parent)
        index = children.index(self.selected_element)
        parent.insert(index + 1, sibling)
        self._after_node_structure_change(sibling, "已新建同级节点，请在中间编辑区填写节点名称、属性或文本")

    def _create_blank_node(self, tag: str = "NEW-NODE") -> ET.Element:
        return ET.Element(tag or "NEW-NODE")

    def default_child_tag(self, parent: ET.Element) -> str:
        children = list(parent)
        if children:
            return children[-1].tag
        parent_name = parent.tag
        if parent_name.endswith("S") and len(parent_name) > 1:
            return parent_name[:-1]
        return "NEW-NODE"

    def _after_node_structure_change(self, element: ET.Element, status: str) -> None:
        self.selected_element = element
        self.set_dirty(True)
        self.refresh_source()
        self.refresh_tree()
        self.refresh_domain_view()
        self.select_element_in_tree(element)
        self.refresh_stats()
        self.render_attribute_editor()
        if hasattr(self, "tag_entry"):
            self.tag_entry.focus_set()
            self.tag_entry.selection_range(0, END)
        self.status_var.set(status)

    def select_element_in_tree(self, element: ET.Element) -> None:
        for item_id, candidate in self.tree_paths.items():
            if candidate is element:
                self.tree.selection_set(item_id)
                self.tree.focus(item_id)
                self.tree.see(item_id)
                return

    def remove_attr_row(self, row: ttk.Frame, pair: tuple[tk.StringVar, tk.StringVar]) -> None:
        if pair in self.attr_rows:
            self.attr_rows.remove(pair)
        row.destroy()

    def apply_attributes(self) -> None:
        self.guarded("应用属性修改", self._apply_attributes)

    def _apply_attributes(self) -> None:
        if self.selected_element is None:
            raise ValueError("请先选择一个 XML 节点")
        selected_path = self.element_path(self.selected_element)
        if self.source_dirty:
            self.sync_source_to_model(selected_path)
        tag = getattr(self, "tag_var", tk.StringVar(value=self.selected_element.tag)).get().strip()
        if not tag:
            raise ValueError("节点名称不能为空")
        if any(ch.isspace() for ch in tag) or tag.startswith("<") or tag.endswith(">"):
            raise ValueError("节点名称不能包含空格或尖括号")
        new_attrs = {}
        for key_var, value_var in getattr(self, "attr_rows", []):
            key = key_var.get().strip()
            if key:
                new_attrs[key] = value_var.get()
        self.selected_element.tag = tag
        self.selected_element.attrib.clear()
        self.selected_element.attrib.update(new_attrs)
        self.selected_element.text = self.text_value.get("1.0", END).strip() or None
        self.set_dirty(True)
        self.refresh_source()
        self.refresh_tree()
        self.refresh_domain_view()
        self.select_element_in_tree(self.selected_element)
        self.refresh_stats()
        self.status_var.set("节点修改已应用")

    def sync_source_to_model(self, selected_path: tuple[int, ...] | None = None) -> None:
        text = self.source.get("1.0", END).strip()
        new_root = parse_xml(text)
        self.xml_root = new_root
        if selected_path is not None:
            self.selected_element = self.element_at_path(new_root, selected_path)
        self.source_dirty = False

    def element_path(self, target: ET.Element) -> tuple[int, ...] | None:
        if self.xml_root is None:
            return None
        if target is self.xml_root:
            return ()

        def walk(parent: ET.Element, path: tuple[int, ...]) -> tuple[int, ...] | None:
            for index, child in enumerate(list(parent)):
                child_path = path + (index,)
                if child is target:
                    return child_path
                found = walk(child, child_path)
                if found is not None:
                    return found
            return None

        return walk(self.xml_root, ())

    def element_at_path(self, root: ET.Element, path: tuple[int, ...] | None) -> ET.Element:
        element = root
        for index in path or ():
            children = list(element)
            if index >= len(children):
                raise ValueError("源码结构已变化，无法定位当前选中节点，请重新选择节点")
            element = children[index]
        return element

    def delete_selected_node(self) -> None:
        self.guarded("删除选中节点", self._delete_selected_node)

    def _delete_selected_node(self) -> None:
        if self.xml_root is None or self.selected_element is None:
            raise ValueError("请先选择一个 XML 节点")
        if self.selected_element is self.xml_root:
            raise ValueError("不能删除根节点")
        parent = self.find_parent(self.xml_root, self.selected_element)
        if parent is None:
            raise ValueError("没有找到父节点")
        parent.remove(self.selected_element)
        self.selected_element = None
        self.set_dirty(True)
        self.refresh_source()
        self.refresh_tree()
        self.refresh_domain_view()
        self.refresh_stats()
        self.clear_attribute_editor("节点已删除")

    def find_parent(self, root: ET.Element, target: ET.Element) -> ET.Element | None:
        for parent in root.iter():
            for child in list(parent):
                if child is target:
                    return parent
        return None

    def on_source_modified(self, _event=None) -> None:
        if self._updating_source:
            self.source.edit_modified(False)
            return
        if self.source.edit_modified():
            self.set_dirty(True)
            self.source_dirty = True
            self.status_var.set("源码已修改，点击检查 XML 或格式化 XML 可同步结构")
            self.logger.debug("XML 源码文本被编辑")
            self.source.edit_modified(False)

    def validate_source(self) -> None:
        self.guarded("检查 XML", self._validate_source)

    def _validate_source(self) -> None:
        text = self.source.get("1.0", END).strip()
        validate_xml(text)
        self.sync_source_to_model(self.element_path(self.selected_element) if self.selected_element is not None else None)
        self.refresh_tree()
        self.refresh_domain_view()
        if self.selected_element is not None:
            self.select_element_in_tree(self.selected_element)
            self.render_attribute_editor()
            self.highlight_selected_source()
        self.refresh_stats()
        self.status_var.set("XML 有效")
        messagebox.showinfo(APP_NAME, "XML 有效")

    def format_source(self) -> None:
        self.guarded("格式化 XML", self._format_source)

    def _format_source(self) -> None:
        text = self.source.get("1.0", END).strip()
        self.xml_root = parse_xml(text)
        self.refresh_source()
        self.refresh_tree()
        self.refresh_domain_view()
        self.refresh_stats()
        self.set_dirty(True)
        self.status_var.set("XML 已格式化并同步结构")

    def save_odx(self) -> None:
        self.guarded("保存 ODX", self._save_odx)

    def _save_odx(self) -> None:
        text = self.current_xml_text()
        if self.current_path and self.current_type == "ODX" and self.current_path.suffix.lower() in {".odx", ".xml"}:
            self.current_path.write_text(text, encoding="utf-8")
            self.set_dirty(False)
            self.refresh_meta()
            self.status_var.set(f"已保存 {self.current_path.name}")
            self.logger.info("直接保存 ODX：%s", self.current_path)
            return
        self._save_as_odx(text)

    def save_as_odx(self) -> None:
        self.guarded("另存为 ODX", self._save_as_odx)

    def _save_as_odx(self, text: str | None = None) -> None:
        text = text if text is not None else self.current_xml_text()
        initial = self.current_path.name if self.current_path and self.current_path.suffix.lower() != ".pdx" else Path(self.xml_entry_name).name
        path_text = filedialog.asksaveasfilename(
            title="另存为 ODX",
            defaultextension=".odx",
            initialfile=initial or "database.odx",
            filetypes=[("ODX", "*.odx"), ("XML", "*.xml"), ("All files", "*.*")],
        )
        self.logger.info("保存路径选择结果：%s", path_text or "<empty>")
        if not path_text:
            return
        path = Path(path_text)
        path.write_text(text, encoding="utf-8")
        self.current_path = path
        self.current_type = "ODX"
        self.xml_entry_name = path.name
        self.set_dirty(False)
        self.refresh_meta()
        self.status_var.set(f"已保存 {path.name}")

    def export_pdx(self) -> None:
        self.guarded("导出 PDX", self._export_pdx)

    def _export_pdx(self) -> None:
        text = self.current_xml_text().encode("utf-8")
        entries = dict(self.pdx_entries)
        entries[self.xml_entry_name or "database.odx"] = text
        initial = self.current_path.stem + ".pdx" if self.current_path else "database.pdx"
        path_text = filedialog.asksaveasfilename(
            title="导出 PDX",
            defaultextension=".pdx",
            initialfile=initial,
            filetypes=[("PDX", "*.pdx"), ("All files", "*.*")],
        )
        self.logger.info("导出 PDX 路径选择结果：%s", path_text or "<empty>")
        if not path_text:
            return
        active_entry = self.xml_entry_name or "database.odx"
        save_pdx(Path(path_text), entries, active_entry, self.current_xml_text())
        entries[active_entry] = text
        for name, data in entries.items():
            self.logger.debug("写入 PDX 条目：%s bytes=%s", name, len(data))
        self.current_path = Path(path_text)
        self.current_type = "PDX"
        self.pdx_entries = entries
        self.set_dirty(False)
        self.refresh_meta()
        self.status_var.set(f"已导出 {Path(path_text).name}")

    def current_xml_text(self) -> str:
        text = self.source.get("1.0", END).strip()
        self.xml_root = parse_xml(text)
        return self.pretty_xml()

    def pretty_xml(self) -> str:
        if self.xml_root is None:
            return ""
        return pretty_xml(self.xml_root)

    def set_dirty(self, dirty: bool) -> None:
        self.dirty = dirty
        self.refresh_meta()

    def confirm_discard_changes(self) -> bool:
        if not self.dirty:
            return True
        return messagebox.askyesno(APP_NAME, "当前文档有未保存修改，是否继续并丢弃这些修改？")

    def on_close(self) -> None:
        if self.confirm_discard_changes():
            self.logger.info("ODX Editor 关闭")
            self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        OdxEditorApp(root)
    except Exception:
        log_dir = app_root() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        crash_log = log_dir / f"startup_crash_{datetime.now():%Y%m%d_%H%M%S}.log"
        crash_log.write_text(traceback.format_exc(), encoding="utf-8")
        messagebox.showerror(APP_NAME, f"启动失败，详情见：\n{crash_log}")
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
