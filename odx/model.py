from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OdxEcu:
    name: str
    address: str
    role: str = "ecu"
    access: str = "direct"


@dataclass(frozen=True)
class OdxDid:
    did: str
    name: str
    description: str = ""
    dop_ref: str | None = None
    response_offset: int = 3


@dataclass(frozen=True)
class OdxComputation:
    name: str
    category: str = "IDENTICAL"
    factor: float = 1.0
    offset: float = 0.0
    denominator: float = 1.0
    unit: str = ""
    unit_ref: str = ""
    lower_limit: float | None = None
    upper_limit: float | None = None
    texttable: dict[int, str] = field(default_factory=dict)

    def apply(self, internal_value: int | float | str) -> int | float | str:
        if isinstance(internal_value, int) and self.category.upper() in {"TEXTTABLE", "TEXT-TABLE"}:
            return self.texttable.get(internal_value, internal_value)
        if not isinstance(internal_value, (int, float)):
            return internal_value
        if self.category.upper() not in {"LINEAR", "SCALE-LINEAR"}:
            return internal_value
        return (internal_value * self.factor + self.offset) / self.denominator

    def inverse(self, physical_value: int | float | str) -> int | float | str:
        if isinstance(physical_value, str) and self.category.upper() in {"TEXTTABLE", "TEXT-TABLE"}:
            for key, label in self.texttable.items():
                if label == physical_value:
                    return key
            return physical_value
        if not isinstance(physical_value, (int, float)):
            return physical_value
        if self.category.upper() not in {"LINEAR", "SCALE-LINEAR"}:
            return physical_value
        if self.factor == 0:
            raise ValueError(f"COMPU-METHOD {self.name} has zero factor")
        return (physical_value * self.denominator - self.offset) / self.factor


@dataclass(frozen=True)
class OdxUnit:
    name: str
    display_name: str = ""
    factor: float | None = None
    offset: float | None = None

    @property
    def label(self) -> str:
        return self.display_name or self.name


@dataclass(frozen=True)
class OdxDataObjectProperty:
    name: str
    base_data_type: str = "A_BYTEFIELD"
    bit_length: int | None = None
    byte_length: int | None = None
    compu_method_ref: str | None = None

    def decode(self, data: bytes, computation: OdxComputation | None = None) -> str:
        payload = data[: self.byte_length] if self.byte_length else data
        data_type = self.base_data_type.upper()
        if data_type in {"A_ASCIISTRING", "ASCII", "STRING"}:
            return payload.decode("ascii", errors="replace").rstrip("\x00")
        if data_type in {"A_UTF8STRING", "UTF8"}:
            return payload.decode("utf-8", errors="replace").rstrip("\x00")
        if data_type in {"A_UINT8", "A_UINT16", "A_UINT32", "A_UINT64", "A_INT8", "A_INT16", "A_INT32", "A_INT64"}:
            signed = data_type.startswith("A_INT")
            value = int.from_bytes(payload, "big", signed=signed)
            physical = computation.apply(value) if computation else value
            suffix = f" {computation.unit}" if computation and computation.unit else ""
            if isinstance(physical, float) and physical.is_integer():
                physical = int(physical)
            return f"{physical}{suffix}"
        return payload.hex(" ").upper()

    def encode(self, value: int | float | str | bytes, computation: OdxComputation | None = None) -> bytes:
        data_type = self.base_data_type.upper()
        length = self.byte_length
        if isinstance(value, bytes):
            payload = value
        elif data_type in {"A_ASCIISTRING", "ASCII", "STRING"}:
            payload = str(value).encode("ascii")
        elif data_type in {"A_UTF8STRING", "UTF8"}:
            payload = str(value).encode("utf-8")
        elif data_type in {"A_UINT8", "A_UINT16", "A_UINT32", "A_UINT64", "A_INT8", "A_INT16", "A_INT32", "A_INT64"}:
            internal = computation.inverse(value) if computation else value
            if isinstance(internal, float):
                if not internal.is_integer():
                    raise ValueError(f"Value {value!r} cannot be encoded as integer for DOP {self.name}")
                internal = int(internal)
            integer = int(internal)
            signed = data_type.startswith("A_INT")
            width = length or max(1, (integer.bit_length() + (8 if signed and integer < 0 else 7)) // 8)
            payload = integer.to_bytes(width, "big", signed=signed)
        elif isinstance(value, str):
            payload = bytes.fromhex(value.replace("0x", "").replace("0X", ""))
        else:
            raise TypeError(f"Unsupported value for DOP {self.name}: {value!r}")

        if length is None:
            return payload
        if len(payload) > length:
            raise ValueError(f"Encoded value for DOP {self.name} is {len(payload)} bytes, expected at most {length}")
        return payload.ljust(length, b"\x00")


@dataclass(frozen=True)
class OdxStructureField:
    name: str
    dop_ref: str | None = None
    semantic: str = ""
    byte_position: int | None = None
    byte_length: int | None = None
    bit_length: int | None = None
    is_required: bool = True


@dataclass(frozen=True)
class OdxStructure:
    name: str
    fields: list[OdxStructureField] = field(default_factory=list)

    def decode(self, data: bytes, dops: dict[str, OdxDataObjectProperty], computations: dict[str, OdxComputation]) -> dict[str, str]:
        values: dict[str, str] = {}
        next_position = 0
        for field in self.fields:
            if not field.dop_ref:
                continue
            dop = dops.get(field.dop_ref)
            if dop is None:
                continue
            position = field.byte_position if field.byte_position is not None else next_position
            length = field.byte_length or dop.byte_length
            payload = data[position : position + length] if length else data[position:]
            computation = computations.get(dop.compu_method_ref or "")
            values[field.name] = dop.decode(payload, computation)
            next_position = position + (length or len(payload))
        return values

    def encode(
        self,
        values: dict[str, int | float | str | bytes],
        dops: dict[str, OdxDataObjectProperty],
        computations: dict[str, OdxComputation],
    ) -> bytes:
        chunks: list[tuple[int, bytes]] = []
        next_position = 0
        for field in self.fields:
            if not field.dop_ref or field.name not in values:
                continue
            dop = dops.get(field.dop_ref)
            if dop is None:
                continue
            position = field.byte_position if field.byte_position is not None else next_position
            computation = computations.get(dop.compu_method_ref or "")
            payload = dop.encode(values[field.name], computation)
            chunks.append((position, payload))
            next_position = position + len(payload)
        if not chunks:
            return b""
        length = max(position + len(payload) for position, payload in chunks)
        encoded = bytearray(length)
        for position, payload in chunks:
            encoded[position : position + len(payload)] = payload
        return bytes(encoded)


@dataclass(frozen=True)
class OdxResponse:
    name: str
    payload_prefix: bytes = b""
    parameters: list["OdxParameter"] = field(default_factory=list)


@dataclass(frozen=True)
class OdxDiagService:
    name: str
    semantic: str = ""
    request: bytes = b""
    positive_response: OdxResponse | None = None
    negative_responses: list["OdxNegativeResponse"] = field(default_factory=list)
    request_parameters: list["OdxParameter"] = field(default_factory=list)


@dataclass(frozen=True)
class OdxRoutine:
    routine_id: str
    name: str
    control: str = "01"


@dataclass(frozen=True)
class OdxDtc:
    code: str
    display_code: str = ""
    description: str = ""
    severity: str = ""


@dataclass(frozen=True)
class OdxNegativeResponse:
    name: str
    payload_prefix: bytes = b""
    nrcs: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class OdxLayer:
    name: str
    layer_type: str = "ecu"
    parent_ref: str | None = None


@dataclass(frozen=True)
class OdxQuickAction:
    label: str
    request: str


@dataclass(frozen=True)
class OdxParameter:
    name: str
    semantic: str = ""
    byte_position: int | None = None
    bit_position: int | None = None
    coded_value: int | None = None
    dop_ref: str | None = None
    param_type: str = ""
    bit_length: int | None = None
    byte_length: int | None = None
    is_required: bool = True
    is_constant: bool = False

    @property
    def is_input(self) -> bool:
        return self.dop_ref is not None and not self.is_constant


@dataclass(frozen=True)
class OdxDatabase:
    ecus: list[OdxEcu] = field(default_factory=list)
    dids: list[OdxDid] = field(default_factory=list)
    routines: list[OdxRoutine] = field(default_factory=list)
    dtcs: list[OdxDtc] = field(default_factory=list)
    layers: list[OdxLayer] = field(default_factory=list)
    quick_actions: list[OdxQuickAction] = field(default_factory=list)
    dops: dict[str, OdxDataObjectProperty] = field(default_factory=dict)
    computations: dict[str, OdxComputation] = field(default_factory=dict)
    units: dict[str, OdxUnit] = field(default_factory=dict)
    structures: dict[str, OdxStructure] = field(default_factory=dict)
    services: list[OdxDiagService] = field(default_factory=list)

    def request_for_did(self, did: str) -> bytes:
        normalized = hex_word(did)
        for service in self.services:
            if len(service.request) >= 3 and service.request[0] == 0x22 and service.request[1:].hex().upper() == normalized:
                return service.request
        return bytes([0x22]) + bytes.fromhex(normalized)

    def decode_did_response(self, did: str, response: bytes) -> str | None:
        normalized = hex_word(did)
        did_definition = next((item for item in self.dids if item.did == normalized), None)
        if did_definition is None or did_definition.dop_ref is None:
            return None
        if len(response) <= did_definition.response_offset:
            return None
        structure = self.structures.get(did_definition.dop_ref)
        if structure is not None:
            values = structure.decode(response[did_definition.response_offset :], self.dops, self.computations)
            return "; ".join(f"{name}={value}" for name, value in values.items())
        dop = self.dops.get(did_definition.dop_ref)
        if dop is None:
            return None
        computation = self.computations.get(dop.compu_method_ref or "")
        return dop.decode(response[did_definition.response_offset :], computation)

    def encode_did_value(self, did: str, value: int | float | str | bytes | dict[str, int | float | str | bytes]) -> bytes | None:
        normalized = hex_word(did)
        did_definition = next((item for item in self.dids if item.did == normalized), None)
        if did_definition is None or did_definition.dop_ref is None:
            return None
        structure = self.structures.get(did_definition.dop_ref)
        if structure is not None:
            if not isinstance(value, dict):
                raise TypeError(f"DID {normalized} expects a dict value for structure {structure.name}")
            return structure.encode(value, self.dops, self.computations)
        dop = self.dops.get(did_definition.dop_ref)
        if dop is None:
            return None
        computation = self.computations.get(dop.compu_method_ref or "")
        return dop.encode(value, computation)

    def encode_service_request(self, service_name: str, values: dict[str, int | float | str | bytes] | None = None) -> bytes | None:
        values = values or {}
        service = next((item for item in self.services if item.name == service_name), None)
        if service is None:
            return None
        if not service.request_parameters:
            return service.request
        chunks: list[tuple[int, bytes]] = []
        next_position = 0
        for parameter in service.request_parameters:
            position = parameter.byte_position if parameter.byte_position is not None else next_position
            if parameter.coded_value is not None:
                width = parameter.byte_length or max(1, (parameter.coded_value.bit_length() + 7) // 8)
                payload = parameter.coded_value.to_bytes(width, "big")
            elif parameter.dop_ref:
                key = first_present(values, parameter.name, parameter.semantic, parameter.dop_ref)
                if key is None:
                    if parameter.is_required:
                        raise ValueError(f"Missing value for service parameter {service.name}.{parameter.name}")
                    continue
                payload = self._encode_ref(parameter.dop_ref, values[key])
                if payload is None:
                    raise ValueError(f"Cannot encode service parameter {service.name}.{parameter.name}")
            else:
                continue
            chunks.append((position, payload))
            next_position = position + len(payload)
        if not chunks:
            return service.request
        length = max(position + len(payload) for position, payload in chunks)
        request = bytearray(length)
        for position, payload in chunks:
            request[position : position + len(payload)] = payload
        return bytes(request)

    def _encode_ref(self, ref: str, value: int | float | str | bytes | dict[str, int | float | str | bytes]) -> bytes | None:
        structure = self.structures.get(ref)
        if structure is not None:
            if not isinstance(value, dict):
                raise TypeError(f"Reference {ref} expects a dict value")
            return structure.encode(value, self.dops, self.computations)
        dop = self.dops.get(ref)
        if dop is None:
            return None
        return dop.encode(value, self.computations.get(dop.compu_method_ref or ""))


def first_present(values: dict[str, object], *keys: str | None) -> str | None:
    for key in keys:
        if key and key in values:
            return key
    return None


def hex_word(value: str) -> str:
    return f"{parse_int(value):04X}"


def hex_byte(value: str) -> str:
    return f"{parse_int(value):02X}"


def hex_trouble_code(value: str) -> str:
    try:
        return f"{parse_int(value):06X}"
    except ValueError:
        return value.strip().upper()


def parse_int(value: str) -> int:
    text = value.strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    if any(character in "ABCDEFabcdef" for character in text):
        return int(text, 16)
    return int(text, 0)
