from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


def parse_hex_bytes(value: str | None) -> bytes:
    if not value:
        return b""
    cleaned = value.replace("0x", "").replace("0X", "").replace(" ", "").replace("-", "")
    if len(cleaned) % 2:
        raise ValueError(f"Odd-length hex string: {value!r}")
    return bytes.fromhex(cleaned)


def parse_int(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(value, 0)


def parse_int_tuple(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    separators = value.replace(";", ",").replace(" ", ",")
    return tuple(parse_int(item) for item in separators.split(",") if item)


@dataclass(frozen=True)
class DataRule:
    did: int | None = None
    request: bytes = b""
    response_mode: str = "static"
    responses: tuple[bytes, ...] = ()
    handler: str = ""
    simulate_pending: bool = False
    total_delay: float = 0.0
    pending_interval: float = 1.0
    required_sessions: tuple[int, ...] = ()
    required_security: str = ""


@dataclass(frozen=True)
class ServiceRule:
    sid: int
    handler: str = ""
    data_rules: tuple[DataRule, ...] = ()
    reset_behavior: str = "state_only"
    reset_delay: float = 0.0
    supported_reset_types: tuple[int, ...] = ()
    restore_dtcs_on_reset: bool = True
    required_sessions: tuple[int, ...] = ()
    required_security: str = ""


@dataclass(frozen=True)
class SecurityLevel:
    name: str
    request_seed: int
    send_key: int
    seed: bytes
    key: bytes
    max_attempts: int = 3
    lock_time: float = 10.0


@dataclass(frozen=True)
class DownloadConfig:
    start_address: int = 0
    end_address: int = 0xFFFFFFFF
    max_block_length: int = 0x400
    required_sessions: tuple[int, ...] = ()
    required_security: str = ""


@dataclass(frozen=True)
class DtcRecord:
    code: int
    status: int
    severity: int = 0
    functional_unit: int = 0
    fault_detection_counter: int = 0
    snapshot: bytes = b""
    extended_data: bytes = b""
    memory: str = "primary"
    permanent: bool = False
    clearable: bool = True
    clear_status: int = 0
    clear_fault_detection_counter: int = 0
    snapshot_record: int = 0x01
    extended_data_record: int = 0x01


@dataclass(frozen=True)
class EcuConfig:
    name: str
    address: int
    role: str = "ecu"
    access: str = "direct"
    gateway_address: int | None = None
    s3_timeout: float = 5.0
    services: dict[int, ServiceRule] = field(default_factory=dict)
    dtcs: tuple[DtcRecord, ...] = ()
    security_levels: dict[int, SecurityLevel] = field(default_factory=dict)
    download: DownloadConfig = field(default_factory=DownloadConfig)


@dataclass(frozen=True)
class SimulatorConfig:
    vin: str
    gateway_address: int
    eid: bytes
    gid: bytes
    ecus: dict[int, EcuConfig]
    allowed_tester_addresses: tuple[int, ...] = ()
    diagnostic_ack: bool = True


class ConfigStore:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._mtime: float | None = None
        self._config: SimulatorConfig | None = None

    @property
    def config(self) -> SimulatorConfig:
        self.reload_if_changed()
        if self._config is None:
            raise RuntimeError("Configuration has not been loaded")
        return self._config

    def reload_if_changed(self) -> bool:
        stat = self.path.stat()
        if self._config is not None and self._mtime == stat.st_mtime:
            return False
        self._config = load_config(self.path)
        self._mtime = stat.st_mtime
        return True


def load_config(path: str | os.PathLike[str]) -> SimulatorConfig:
    root = ET.parse(path).getroot()
    if root.tag != "Simulator":
        raise ValueError("Root element must be <Simulator>")

    vin = root.attrib.get("vin", "SIMULATOR0000000")
    gateway_address = parse_int(root.attrib.get("logical_address"), 0x0E00)
    eid = parse_hex_bytes(root.attrib.get("eid", "00 11 22 33 44 55"))
    gid = parse_hex_bytes(root.attrib.get("gid", "AA BB CC DD EE FF"))
    doip_node = root.find("./DoIP")
    allowed_tester_addresses = parse_int_tuple(doip_node.attrib.get("allowed_testers")) if doip_node is not None else ()
    diagnostic_ack = doip_node.attrib.get("diagnostic_ack", "true").lower() == "true" if doip_node is not None else True

    ecus: dict[int, EcuConfig] = {}
    for ecu_node in root.findall("./Ecus/Ecu"):
        address = parse_int(ecu_node.attrib.get("address"))
        services: dict[int, ServiceRule] = {}
        for service_node in ecu_node.findall("./Service"):
            sid = parse_int(service_node.attrib.get("id"))
            service_handler = service_node.attrib.get("handler", "")
            data_rules = tuple(_parse_data_rule(data_node) for data_node in service_node.findall("./Data"))
            services[sid] = ServiceRule(
                sid=sid,
                handler=service_handler,
                data_rules=data_rules,
                reset_behavior=service_node.attrib.get("reset_behavior", "state_only"),
                reset_delay=float(service_node.attrib.get("reset_delay", "0")),
                supported_reset_types=parse_int_tuple(service_node.attrib.get("supported_reset_types")),
                restore_dtcs_on_reset=service_node.attrib.get("restore_dtcs_on_reset", "true").lower() == "true",
                required_sessions=parse_int_tuple(service_node.attrib.get("required_session")),
                required_security=service_node.attrib.get("required_security", ""),
            )
        ecus[address] = EcuConfig(
            name=ecu_node.attrib.get("name", f"ECU_{address:04X}"),
            address=address,
            role=ecu_node.attrib.get("role", "ecu").lower(),
            access=ecu_node.attrib.get("access", "direct").lower(),
            gateway_address=parse_int(ecu_node.attrib["gateway"]) if "gateway" in ecu_node.attrib else None,
            s3_timeout=float(ecu_node.attrib.get("s3_timeout", "5.0")),
            services=services,
            dtcs=tuple(_parse_dtc(dtc_node) for dtc_node in ecu_node.findall("./Dtcs/Dtc")),
            security_levels=_parse_security_levels(ecu_node),
            download=_parse_download_config(ecu_node),
        )

    return SimulatorConfig(
        vin=vin,
        gateway_address=gateway_address,
        eid=eid,
        gid=gid,
        ecus=ecus,
        allowed_tester_addresses=allowed_tester_addresses,
        diagnostic_ack=diagnostic_ack,
    )


def _parse_data_rule(data_node: ET.Element) -> DataRule:
    responses = tuple(
        parse_hex_bytes(response_node.text or response_node.attrib.get("value", ""))
        for response_node in data_node.findall("./Response")
    )
    if not responses and (data_node.text or "").strip():
        responses = (parse_hex_bytes(data_node.text),)

    return DataRule(
        did=parse_int(data_node.attrib["did"]) if "did" in data_node.attrib else None,
        request=parse_hex_bytes(data_node.attrib.get("request")),
        response_mode=data_node.attrib.get("response_mode", "static"),
        responses=responses,
        handler=data_node.attrib.get("handler", ""),
        simulate_pending=data_node.attrib.get("simulate_pending", "false").lower() == "true",
        total_delay=float(data_node.attrib.get("total_delay", "0")),
        pending_interval=float(data_node.attrib.get("pending_interval", "1.0")),
        required_sessions=parse_int_tuple(data_node.attrib.get("required_session")),
        required_security=data_node.attrib.get("required_security", ""),
    )


def _parse_dtc(dtc_node: ET.Element) -> DtcRecord:
    return DtcRecord(
        code=parse_int(dtc_node.attrib.get("code")),
        status=parse_int(dtc_node.attrib.get("status"), 0x09) & 0xFF,
        severity=parse_int(dtc_node.attrib.get("severity"), 0) & 0xFF,
        functional_unit=parse_int(dtc_node.attrib.get("functional_unit"), 0) & 0xFF,
        fault_detection_counter=parse_int(dtc_node.attrib.get("fault_detection_counter"), 0) & 0xFF,
        snapshot=parse_hex_bytes(dtc_node.attrib.get("snapshot")),
        extended_data=parse_hex_bytes(dtc_node.attrib.get("extended_data")),
        memory=dtc_node.attrib.get("memory", "primary"),
        permanent=dtc_node.attrib.get("permanent", "false").lower() == "true",
        clearable=dtc_node.attrib.get("clearable", "true").lower() == "true",
        clear_status=parse_int(dtc_node.attrib.get("clear_status"), 0) & 0xFF,
        clear_fault_detection_counter=parse_int(dtc_node.attrib.get("clear_fault_detection_counter"), 0) & 0xFF,
        snapshot_record=parse_int(dtc_node.attrib.get("snapshot_record"), 0x01) & 0xFF,
        extended_data_record=parse_int(dtc_node.attrib.get("extended_data_record"), 0x01) & 0xFF,
    )


def _parse_security_levels(ecu_node: ET.Element) -> dict[int, SecurityLevel]:
    levels: dict[int, SecurityLevel] = {}
    for level_node in ecu_node.findall("./Security/Level"):
        request_seed = parse_int(level_node.attrib.get("request_seed"))
        send_key = parse_int(level_node.attrib.get("send_key"))
        level = SecurityLevel(
            name=level_node.attrib.get("name", f"level_{request_seed:02X}"),
            request_seed=request_seed,
            send_key=send_key,
            seed=parse_hex_bytes(level_node.attrib.get("seed", "12 34 56 78")),
            key=parse_hex_bytes(level_node.attrib.get("key", "87 65 43 21")),
            max_attempts=parse_int(level_node.attrib.get("max_attempts"), 3),
            lock_time=float(level_node.attrib.get("lock_time", "10.0")),
        )
        levels[level.request_seed] = level
        levels[level.send_key] = level
    return levels


def _parse_download_config(ecu_node: ET.Element) -> DownloadConfig:
    download_node = ecu_node.find("./Download")
    if download_node is None:
        return DownloadConfig()
    return DownloadConfig(
        start_address=parse_int(download_node.attrib.get("start_address"), 0),
        end_address=parse_int(download_node.attrib.get("end_address"), 0xFFFFFFFF),
        max_block_length=parse_int(download_node.attrib.get("max_block_length"), 0x400),
        required_sessions=parse_int_tuple(download_node.attrib.get("required_session")),
        required_security=download_node.attrib.get("required_security", ""),
    )
