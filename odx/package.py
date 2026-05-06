from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ODX_XML_SUFFIXES = (".odx", ".xml")
PDX_SUFFIXES = {".pdx", ".zip"}


@dataclass
class OdxPackage:
    source_path: Path
    active_entry: str
    entries: dict[str, bytes] = field(default_factory=dict)

    @property
    def is_pdx(self) -> bool:
        return self.source_path.suffix.lower() in PDX_SUFFIXES

    @property
    def xml_text(self) -> str:
        data = self.entries[self.active_entry]
        return data.decode("utf-8-sig")

    def with_xml_text(self, text: str) -> "OdxPackage":
        entries = dict(self.entries)
        entries[self.active_entry] = text.encode("utf-8")
        return OdxPackage(self.source_path, self.active_entry, entries)


def open_odx_package(path: Path, active_entry: str | None = None) -> OdxPackage:
    path = Path(path)
    if path.suffix.lower() in PDX_SUFFIXES:
        return open_pdx(path, active_entry)
    return OdxPackage(source_path=path, active_entry=path.name, entries={path.name: path.read_bytes()})


def open_pdx(path: Path, active_entry: str | None = None) -> OdxPackage:
    entries: dict[str, bytes] = {}
    with ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if not info.is_dir():
                entries[info.filename] = archive.read(info.filename)
    xml_entries = xml_entry_names(entries)
    if not xml_entries:
        raise ValueError(f"No ODX/XML files found in PDX: {path}")
    selected = active_entry or xml_entries[0]
    if selected not in entries:
        raise ValueError(f"ODX/XML entry not found in PDX: {selected}")
    return OdxPackage(source_path=path, active_entry=selected, entries=entries)


def xml_entry_names(entries: dict[str, bytes]) -> list[str]:
    return [name for name in entries if name.lower().endswith(ODX_XML_SUFFIXES)]


def save_pdx(path: Path, entries: dict[str, bytes], active_entry: str, xml_text: str) -> None:
    output_entries = dict(entries)
    output_entries[active_entry] = xml_text.encode("utf-8")
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in output_entries.items():
            archive.writestr(name, data)
