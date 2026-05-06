from __future__ import annotations

from xml.dom import minidom
from xml.etree import ElementTree as ET


def parse_xml(text: str | bytes) -> ET.Element:
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig")
    return ET.fromstring(text)


def parse_xml_file(path) -> ET.Element:
    return ET.parse(path).getroot()


def pretty_xml(root_or_text: ET.Element | str | bytes) -> str:
    root = parse_xml(root_or_text) if isinstance(root_or_text, (str, bytes)) else root_or_text
    rough = ET.tostring(root, encoding="utf-8")
    parsed = minidom.parseString(rough)
    body = parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    lines = [line for line in body.splitlines() if line.strip()]
    return "\n".join(lines) + "\n"


def validate_xml(text: str | bytes) -> None:
    parse_xml(text)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find_all(root: ET.Element, name: str) -> list[ET.Element]:
    return [element for element in root.iter() if local_name(element.tag) == name]


def find_all_any(root: ET.Element, names: set[str]) -> list[ET.Element]:
    return [element for element in root.iter() if local_name(element.tag) in names]


def child_text(root: ET.Element, name: str) -> str | None:
    for child in root:
        if local_name(child.tag) == name and child.text:
            return child.text.strip()
    return None


def child_text_any(root: ET.Element, names: tuple[str, ...]) -> str | None:
    for name in names:
        value = child_text(root, name)
        if value:
            return value
    return None


def first_child(root: ET.Element, name: str) -> ET.Element | None:
    for child in root:
        if local_name(child.tag) == name:
            return child
    return None


def first_descendant(root: ET.Element, name: str) -> ET.Element | None:
    for element in root.iter():
        if element is not root and local_name(element.tag) == name:
            return element
    return None


def first_descendant_any(root: ET.Element, names: set[str]) -> ET.Element | None:
    for element in root.iter():
        if element is not root and local_name(element.tag) in names:
            return element
    return None


def attr(element: ET.Element, *names: str) -> str | None:
    for name in names:
        if name in element.attrib and element.attrib[name].strip():
            return element.attrib[name].strip()
    return None


def attr_or_child(element: ET.Element, *names: str) -> str | None:
    value = attr(element, *names)
    if value:
        return value
    return child_text_any(element, tuple(names))
