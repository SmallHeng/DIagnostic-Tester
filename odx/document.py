from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from .xml_tools import local_name, parse_xml, parse_xml_file, pretty_xml


@dataclass(frozen=True)
class OdxNode:
    path: tuple[int, ...]
    tag: str
    node_type: str
    attributes: dict[str, str]
    text: str = ""


@dataclass
class OdxDocument:
    root: ET.Element
    source_path: Path | None = None
    dirty: bool = False
    nodes: list[OdxNode] = field(default_factory=list)

    @classmethod
    def from_text(cls, text: str | bytes, source_path: Path | None = None) -> "OdxDocument":
        document = cls(root=parse_xml(text), source_path=source_path)
        document.refresh_nodes()
        return document

    @classmethod
    def from_file(cls, path: Path) -> "OdxDocument":
        document = cls(root=parse_xml_file(path), source_path=Path(path))
        document.refresh_nodes()
        return document

    def refresh_nodes(self) -> None:
        self.nodes = []
        self._walk(self.root, ())

    def to_xml(self) -> str:
        return pretty_xml(self.root)

    def mark_dirty(self) -> None:
        self.dirty = True

    def _walk(self, element: ET.Element, path: tuple[int, ...]) -> None:
        self.nodes.append(
            OdxNode(
                path=path,
                tag=element.tag,
                node_type=classify_node(element),
                attributes=dict(element.attrib),
                text=(element.text or "").strip(),
            )
        )
        for index, child in enumerate(list(element)):
            self._walk(child, path + (index,))


def classify_node(element: ET.Element) -> str:
    name = local_name(element.tag)
    if name in {"DIAG-LAYER", "ECU-VARIANT", "BASE-VARIANT", "PROTOCOL", "FUNCTIONAL-GROUP"}:
        return "layer"
    if name in {"DATA-IDENTIFIER", "DATA-IDENT"}:
        return "did"
    if name == "DATA-OBJECT-PROP":
        return "dop"
    if name == "DIAG-SERVICE":
        return "service"
    if name in {"REQUEST", "POS-RESPONSE", "NEG-RESPONSE"}:
        return "message"
    if name == "PARAM":
        return "parameter"
    return "xml"
