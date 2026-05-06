from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from .model import (
    OdxComputation,
    OdxDatabase,
    OdxDataObjectProperty,
    OdxDiagService,
    OdxDid,
    OdxDtc,
    OdxEcu,
    OdxLayer,
    OdxNegativeResponse,
    OdxParameter,
    OdxQuickAction,
    OdxResponse,
    OdxRoutine,
    OdxStructure,
    OdxStructureField,
    OdxUnit,
    hex_byte,
    hex_trouble_code,
    hex_word,
)
from .package import open_pdx
from .xml_tools import (
    attr,
    attr_or_child,
    child_text,
    child_text_any,
    find_all,
    find_all_any,
    first_child,
    first_descendant,
    first_descendant_any,
    local_name,
    parse_xml_file,
)


LAYER_NAMES = {"DIAG-LAYER", "ECU-VARIANT", "BASE-VARIANT", "PROTOCOL", "FUNCTIONAL-GROUP"}
DID_NAMES = {"DATA-IDENTIFIER", "DATA-IDENT"}


def load_odx(path: Path) -> OdxDatabase:
    path = Path(path)
    if path.suffix.lower() in {".pdx", ".zip"}:
        return load_pdx(path)
    return load_odx_root(parse_xml_file(path))


def load_pdx(path: Path) -> OdxDatabase:
    package = open_pdx(Path(path))
    databases = []
    for name in package.entries:
        if name.lower().endswith((".odx", ".xml")):
            databases.append(load_odx_root(ET.fromstring(package.entries[name])))
    if not databases:
        raise ValueError(f"No ODX/XML files found in PDX: {path}")
    return merge_databases(databases)


def load_odx_root(root: ET.Element) -> OdxDatabase:
    ecus: list[OdxEcu] = []
    layers: list[OdxLayer] = []
    dids: dict[str, OdxDid] = {}
    routines: dict[str, OdxRoutine] = {}
    dtcs: dict[str, OdxDtc] = {}
    quick_actions: list[OdxQuickAction] = []
    dops = load_dops(root)
    units = load_units(root)
    computations = load_computations(root, units)
    structures = load_structures(root)
    services = load_services(root)
    dtcs.update({dtc.code: dtc for dtc in load_dtcs(root)})

    for layer in find_all_any(root, LAYER_NAMES):
        name = short_name(layer) or "ECU"
        address = (
            attr_or_child(layer, "LOGICAL-ADDRESS", "logical-address", "address", "PHYSICAL-ADDRESS", "physical-address", "PHYS-ADDR", "phys-addr")
            or "0x1001"
        )
        role = attr_or_child(layer, "ROLE", "role", "TYPE", "type") or default_layer_role(layer)
        access = attr_or_child(layer, "ACCESS", "access") or "direct"
        ecus.append(OdxEcu(name=name, address=hex_word(address), role=role, access=access))
        layers.append(OdxLayer(name=name, layer_type=local_name(layer.tag), parent_ref=ref_value(layer, "PARENT-REF") or ref_value(layer, "BASE-VARIANT-REF")))

        for did_element in find_all_any(layer, DID_NAMES):
            did = did_value(did_element)
            if not did:
                continue
            did_key = hex_word(did)
            dids[did_key] = OdxDid(
                did=did_key,
                name=short_name(did_element) or did_key,
                description=attr_or_child(did_element, "DESC", "desc", "description", "DESC-TEXT") or "",
                dop_ref=ref_value(did_element, "DOP-REF") or attr(did_element, "DOP-REF", "dop-ref", "dop"),
                response_offset=int(attr(did_element, "RESPONSE-OFFSET", "response-offset") or "3", 0),
            )

        for routine_element in find_all(layer, "ROUTINE"):
            routine_id = attr(routine_element, "ID", "id", "RID", "rid") or child_text(routine_element, "ID")
            if not routine_id:
                continue
            routine_key = hex_word(routine_id)
            routines[routine_key] = OdxRoutine(
                routine_id=routine_key,
                name=attr(routine_element, "SHORT-NAME", "short-name", "name") or child_text(routine_element, "SHORT-NAME") or routine_key,
                control=hex_byte(attr(routine_element, "CONTROL", "control") or "0x01"),
            )

    for action in find_all(root, "ACTION"):
        request = attr(action, "REQUEST", "request") or child_text(action, "REQUEST")
        if not request:
            continue
        quick_actions.append(
            OdxQuickAction(
                label=attr(action, "SHORT-NAME", "short-name", "name", "LABEL", "label") or child_text(action, "SHORT-NAME") or request,
                request=request,
            )
        )

    return OdxDatabase(
        ecus=ecus,
        dids=list(dids.values()),
        routines=list(routines.values()),
        dtcs=list(dtcs.values()),
        layers=layers,
        quick_actions=quick_actions,
        dops=dops,
        computations=computations,
        units=units,
        structures=structures,
        services=services,
    )


def load_units(root: ET.Element) -> dict[str, OdxUnit]:
    units: dict[str, OdxUnit] = {}
    for element in find_all(root, "UNIT"):
        name = short_name(element)
        if not name:
            continue
        units[name] = OdxUnit(
            name=name,
            display_name=(
                attr_or_child(element, "DISPLAY-NAME", "display-name", "TEXT", "text")
                or child_text(element, "DESC")
                or name
            ),
            factor=float(value) if (value := attr_or_child(element, "FACTOR-SI-TO-UNIT", "factor-si-to-unit", "FACTOR", "factor")) else None,
            offset=float(value) if (value := attr_or_child(element, "OFFSET-SI-TO-UNIT", "offset-si-to-unit", "OFFSET", "offset")) else None,
        )
    return units


def load_dops(root: ET.Element) -> dict[str, OdxDataObjectProperty]:
    dops: dict[str, OdxDataObjectProperty] = {}
    for element in find_all(root, "DATA-OBJECT-PROP"):
        name = short_name(element)
        if not name:
            continue
        coded_type = first_descendant(element, "DIAG-CODED-TYPE")
        length_type = first_descendant_any(element, {"STANDARD-LENGTH-TYPE", "MIN-MAX-LENGTH-TYPE", "LEADING-LENGTH-INFO-TYPE"})
        base_type = (
            attr(element, "BASE-DATA-TYPE", "base-data-type")
            or (coded_type is not None and attr(coded_type, "BASE-DATA-TYPE", "base-data-type"))
            or (length_type is not None and attr(length_type, "BASE-DATA-TYPE", "base-data-type"))
            or child_text(element, "BASE-DATA-TYPE")
            or "A_BYTEFIELD"
        )
        bit_length_text = (
            attr(element, "BIT-LENGTH", "bit-length")
            or (coded_type is not None and attr(coded_type, "BIT-LENGTH", "bit-length"))
            or (length_type is not None and attr(length_type, "BIT-LENGTH", "bit-length"))
            or child_text(element, "BIT-LENGTH")
        )
        byte_length_text = (
            attr(element, "BYTE-LENGTH", "byte-length")
            or (coded_type is not None and attr(coded_type, "BYTE-LENGTH", "byte-length"))
            or (length_type is not None and attr(length_type, "BYTE-LENGTH", "byte-length"))
            or child_text(element, "BYTE-LENGTH")
        )
        bit_length = int(bit_length_text, 0) if bit_length_text else None
        byte_length = int(byte_length_text, 0) if byte_length_text else ((bit_length + 7) // 8 if bit_length else None)
        dops[name] = OdxDataObjectProperty(
            name=name,
            base_data_type=str(base_type),
            bit_length=bit_length,
            byte_length=byte_length,
            compu_method_ref=ref_value(element, "COMPU-METHOD-REF") or attr(element, "COMPU-METHOD-REF", "compu-method-ref"),
        )
    return dops


def load_computations(root: ET.Element, units: dict[str, OdxUnit] | None = None) -> dict[str, OdxComputation]:
    computations: dict[str, OdxComputation] = {}
    units = units or {}
    for element in find_all(root, "COMPU-METHOD"):
        name = short_name(element)
        if not name:
            continue
        category = attr(element, "CATEGORY", "category") or child_text(element, "CATEGORY") or "IDENTICAL"
        values = [float(value.text.strip()) for value in find_all(element, "V") if value.text and value.text.strip()]
        offset = values[0] if len(values) >= 1 else float(attr(element, "OFFSET", "offset") or 0)
        factor = values[1] if len(values) >= 2 else float(attr(element, "FACTOR", "factor") or 1)
        denominator = values[2] if len(values) >= 3 else float(attr(element, "DENOMINATOR", "denominator") or 1)
        scales = find_all(element, "COMPU-SCALE")
        texttable = load_texttable(scales)
        lower_limit, upper_limit = load_limits(element)
        if category.upper() in {"TEXTTABLE", "TEXT-TABLE"} and not texttable:
            texttable = load_texttable(find_all(element, "SCALE"))
        unit_ref = ref_value(element, "UNIT-REF") or attr(element, "UNIT-REF", "unit-ref") or ""
        unit_label = attr(element, "UNIT", "unit") or child_text(element, "UNIT") or ""
        if not unit_label and unit_ref in units:
            unit_label = units[unit_ref].label
        computations[name] = OdxComputation(
            name=name,
            category=category,
            factor=factor,
            offset=offset,
            denominator=denominator,
            unit=unit_label,
            unit_ref=unit_ref,
            lower_limit=lower_limit,
            upper_limit=upper_limit,
            texttable=texttable,
        )
    return computations


def load_structures(root: ET.Element) -> dict[str, OdxStructure]:
    structures: dict[str, OdxStructure] = {}
    for element in find_all(root, "STRUCTURE") + find_all(root, "END-OF-PDU-FIELD"):
        name = short_name(element)
        if not name:
            continue
        fields = []
        for index, parameter in enumerate(find_all(element, "PARAM")):
            param = parameter_from_element(parameter, index)
            fields.append(
                OdxStructureField(
                    name=param.name,
                    dop_ref=param.dop_ref,
                    semantic=param.semantic,
                    byte_position=param.byte_position,
                    byte_length=param.byte_length,
                    bit_length=param.bit_length,
                    is_required=param.is_required,
                )
            )
        for index, field in enumerate(find_all(element, "STRUCTURE-FIELD")):
            fields.append(
                OdxStructureField(
                    name=short_name(field) or attr_or_child(field, "SEMANTIC", "semantic") or f"FIELD.{index + 1}",
                    dop_ref=ref_value(field, "DOP-REF") or ref_value(field, "STRUCTURE-REF") or attr_or_child(field, "DOP-REF", "dop-ref"),
                    semantic=attr_or_child(field, "SEMANTIC", "semantic") or "",
                    byte_position=int(value, 0) if (value := attr_or_child(field, "BYTE-POSITION", "byte-position")) else None,
                    byte_length=int(value, 0) if (value := attr_or_child(field, "BYTE-LENGTH", "byte-length")) else None,
                    bit_length=int(value, 0) if (value := attr_or_child(field, "BIT-LENGTH", "bit-length")) else None,
                    is_required=(attr_or_child(field, "OPTIONAL", "optional") or "").lower() not in {"true", "1", "yes"},
                )
            )
        structures[name] = OdxStructure(name=name, fields=fields)
    return structures


def load_services(root: ET.Element) -> list[OdxDiagService]:
    services: list[OdxDiagService] = []
    for element in find_all(root, "DIAG-SERVICE"):
        request_parameters: list[OdxParameter] = []
        response_parameters: list[OdxParameter] = []
        request = bytes_from_text(attr(element, "REQUEST", "request") or child_text(element, "REQUEST"))
        if request is None:
            request_ref = ref_value(element, "REQUEST-REF") or snref_value(element, "REQUEST-SNREF")
            if request_ref:
                request, request_parameters = request_by_name(root, request_ref)
        if request is None:
            request_element = first_child(element, "REQUEST")
            if request_element is not None:
                request_parameters = parameters_from_element(request_element)
                request = bytes_from_params(request_element)
        response_prefix = bytes_from_text(
            attr(element, "POS-RESPONSE", "pos-response", "POSITIVE-RESPONSE", "positive-response")
            or child_text(element, "POS-RESPONSE")
            or child_text(element, "POS-RESPONSE-REF")
        )
        if response_prefix is None:
            response_ref = ref_value(element, "POS-RESPONSE-REF") or snref_value(element, "POS-RESPONSE-SNREF")
            if response_ref:
                response_prefix, response_parameters = response_by_name(root, response_ref)
        if response_prefix is None:
            response_element = first_child(element, "POS-RESPONSE") or first_child(element, "POSITIVE-RESPONSE")
            if response_element is not None:
                response_parameters = parameters_from_element(response_element)
                response_prefix = bytes_from_params(response_element)
        services.append(
            OdxDiagService(
                name=short_name(element) or "DIAG-SERVICE",
                semantic=attr(element, "SEMANTIC", "semantic") or "",
                request=request or b"",
                positive_response=OdxResponse(name="POS-RESPONSE", payload_prefix=response_prefix or b"", parameters=response_parameters),
                negative_responses=negative_responses_for_service(root, element),
                request_parameters=request_parameters,
            )
        )
    return services


def load_texttable(scales: list[ET.Element]) -> dict[int, str]:
    table: dict[int, str] = {}
    for scale in scales:
        label = attr_or_child(scale, "TEXT", "text", "VT", "SHORT-LABEL", "short-label")
        if not label:
            vt = first_descendant(scale, "VT")
            label = vt.text.strip() if vt is not None and vt.text else None
        lower = attr_or_child(scale, "LOWER-LIMIT", "lower-limit")
        upper = attr_or_child(scale, "UPPER-LIMIT", "upper-limit")
        key_text = lower or upper or attr_or_child(scale, "VALUE", "value")
        if label and key_text:
            table[int(float(key_text))] = label
    return table


def load_limits(element: ET.Element) -> tuple[float | None, float | None]:
    lower = attr_or_child(element, "LOWER-LIMIT", "lower-limit")
    upper = attr_or_child(element, "UPPER-LIMIT", "upper-limit")
    return (float(lower) if lower else None, float(upper) if upper else None)


def negative_responses_for_service(root: ET.Element, service: ET.Element) -> list[OdxNegativeResponse]:
    responses: list[OdxNegativeResponse] = []
    refs = [ref_value(service, "NEG-RESPONSE-REF"), snref_value(service, "NEG-RESPONSE-SNREF")]
    for ref in [item for item in refs if item]:
        response = negative_response_by_name(root, ref)
        if response is not None:
            responses.append(response)
    for response_element in find_all(service, "NEG-RESPONSE"):
        responses.append(negative_response_from_element(response_element))
    return responses


def negative_response_by_name(root: ET.Element, name: str) -> OdxNegativeResponse | None:
    for response in find_all(root, "NEG-RESPONSE"):
        if short_name(response) == name:
            return negative_response_from_element(response)
    return None


def negative_response_from_element(element: ET.Element) -> OdxNegativeResponse:
    payload = bytes_from_text(attr(element, "BYTES", "bytes") or child_text(element, "BYTES")) or bytes_from_params(element) or b""
    nrcs = [
        int(value, 0)
        for value in [
            attr_or_child(nrc, "CODED-VALUE", "coded-value", "NRC", "nrc")
            for nrc in find_all(element, "NRC-CONST")
        ]
        if value
    ]
    return OdxNegativeResponse(name=short_name(element) or "NEG-RESPONSE", payload_prefix=payload, nrcs=nrcs)


def load_dtcs(root: ET.Element) -> list[OdxDtc]:
    dtcs: dict[str, OdxDtc] = {}
    for element in find_all(root, "DTC"):
        code = attr_or_child(element, "TROUBLE-CODE", "trouble-code", "CODE", "code", "DTC", "dtc")
        if not code:
            continue
        normalized = hex_trouble_code(code)
        dtcs[normalized] = OdxDtc(
            code=normalized,
            display_code=attr_or_child(element, "DISPLAY-TROUBLE-CODE", "display-trouble-code", "SHORT-NAME", "short-name") or short_name(element) or normalized,
            description=attr_or_child(element, "TEXT", "text", "DESC", "desc", "description") or child_text(element, "DESC") or "",
            severity=attr_or_child(element, "SEVERITY", "severity") or "",
        )
    return list(dtcs.values())


def request_by_name(root: ET.Element, name: str) -> tuple[bytes | None, list[OdxParameter]]:
    for request in find_all(root, "REQUEST"):
        if short_name(request) == name:
            parameters = parameters_from_element(request)
            payload = bytes_from_text(attr(request, "BYTES", "bytes") or child_text(request, "BYTES")) or bytes_from_params(request)
            return payload, parameters
    return None, []


def response_by_name(root: ET.Element, name: str) -> tuple[bytes | None, list[OdxParameter]]:
    for response in find_all(root, "POS-RESPONSE") + find_all(root, "POSITIVE-RESPONSE"):
        if short_name(response) == name:
            parameters = parameters_from_element(response)
            payload = (
                bytes_from_text(attr(response, "BYTES", "bytes", "POS-RESPONSE", "positive-response") or child_text(response, "BYTES"))
                or bytes_from_params(response)
            )
            return payload, parameters
    return None, []


def merge_databases(databases: list[OdxDatabase]) -> OdxDatabase:
    ecus: list[OdxEcu] = []
    dids: dict[str, OdxDid] = {}
    routines: dict[str, OdxRoutine] = {}
    dtcs: dict[str, OdxDtc] = {}
    layers: list[OdxLayer] = []
    quick_actions: list[OdxQuickAction] = []
    dops: dict[str, OdxDataObjectProperty] = {}
    computations: dict[str, OdxComputation] = {}
    units: dict[str, OdxUnit] = {}
    structures: dict[str, OdxStructure] = {}
    services: list[OdxDiagService] = []
    for database in databases:
        ecus.extend(database.ecus)
        dids.update({did.did: did for did in database.dids})
        routines.update({routine.routine_id: routine for routine in database.routines})
        dtcs.update({dtc.code: dtc for dtc in database.dtcs})
        layers.extend(database.layers)
        quick_actions.extend(database.quick_actions)
        dops.update(database.dops)
        computations.update(database.computations)
        units.update(database.units)
        structures.update(database.structures)
        services.extend(database.services)
    return OdxDatabase(
        ecus=ecus,
        dids=list(dids.values()),
        routines=list(routines.values()),
        dtcs=list(dtcs.values()),
        layers=layers,
        quick_actions=quick_actions,
        dops=dops,
        computations=computations,
        units=units,
        structures=structures,
        services=services,
    )


def short_name(element: ET.Element) -> str | None:
    return attr(element, "SHORT-NAME", "short-name") or child_text(element, "SHORT-NAME") or attr(element, "ID", "id", "name")


def default_layer_role(element: ET.Element) -> str:
    name = local_name(element.tag)
    if name == "PROTOCOL":
        return "protocol"
    if name == "FUNCTIONAL-GROUP":
        return "functional-group"
    return "ecu"


def did_value(element: ET.Element) -> str | None:
    semantic_value = attr_or_child(
        element,
        "ID",
        "DID",
        "DATA-ID",
        "IDENT-VALUE",
        "DIAG-CODE",
        "id",
        "did",
        "data-id",
        "diag-code",
        "ident-value",
    )
    if local_name(element.tag) == "DATA-IDENT":
        semantic_value = attr_or_child(
            element,
            "DID",
            "DATA-ID",
            "IDENT-VALUE",
            "DIAG-CODE",
            "did",
            "data-id",
            "ident-value",
            "diag-code",
        )
    return semantic_value


def ref_value(element: ET.Element, local_name: str) -> str | None:
    ref = first_child(element, local_name)
    if ref is None:
        return None
    value = attr(ref, "ID-REF", "id-ref", "REF", "ref")
    if value:
        return value.rsplit("/", 1)[-1]
    if ref.text and ref.text.strip():
        return ref.text.strip().rsplit("/", 1)[-1]
    return None


def snref_value(element: ET.Element, local_name: str) -> str | None:
    ref = first_child(element, local_name)
    if ref is None:
        return None
    return attr(ref, "SHORT-NAME", "short-name", "SNREF", "snref")


def bytes_from_text(value: str | None) -> bytes | None:
    if not value:
        return None
    normalized = value.replace(",", " ").replace("0x", "").replace("0X", "")
    parts = [part for part in normalized.split() if part]
    if not parts:
        return None
    return bytes(int(part, 16) for part in parts)


def bytes_from_params(element: ET.Element) -> bytes | None:
    values: list[tuple[int, int]] = []
    next_position = 0
    for param in find_all(element, "PARAM"):
        coded_value = param_coded_value(param)
        if coded_value is None:
            continue
        position_text = attr_or_child(param, "BYTE-POSITION", "byte-position")
        position = int(position_text, 0) if position_text else next_position
        values.append((position, coded_value))
        next_position = max(next_position, position + max(1, (coded_value.bit_length() + 7) // 8))
    if not values:
        return None

    length = max(position + max(1, (value.bit_length() + 7) // 8) for position, value in values)
    payload = bytearray(length)
    for position, value in values:
        width = max(1, (value.bit_length() + 7) // 8)
        payload[position : position + width] = value.to_bytes(width, "big")
    return bytes(payload)


def parameters_from_element(element: ET.Element) -> list[OdxParameter]:
    return [parameter_from_element(param, index) for index, param in enumerate(find_all(element, "PARAM"))]


def parameter_from_element(param: ET.Element, index: int) -> OdxParameter:
    name = short_name(param) or attr_or_child(param, "SEMANTIC", "semantic") or f"PARAM.{index + 1}"
    byte_position = int(value, 0) if (value := attr_or_child(param, "BYTE-POSITION", "byte-position")) else None
    bit_position = int(value, 0) if (value := attr_or_child(param, "BIT-POSITION", "bit-position")) else None
    bit_length = int(value, 0) if (value := attr_or_child(param, "BIT-LENGTH", "bit-length")) else None
    byte_length = int(value, 0) if (value := attr_or_child(param, "BYTE-LENGTH", "byte-length")) else ((bit_length + 7) // 8 if bit_length else None)
    coded_value = param_coded_value(param)
    semantic = attr_or_child(param, "SEMANTIC", "semantic") or ""
    param_type = attr_or_child(param, "TYPE", "type") or local_name(param.tag)
    return OdxParameter(
        name=name,
        semantic=semantic,
        byte_position=byte_position,
        bit_position=bit_position,
        coded_value=coded_value,
        dop_ref=ref_value(param, "DOP-REF") or ref_value(param, "STRUCTURE-REF") or attr_or_child(param, "DOP-REF", "dop-ref"),
        param_type=param_type,
        bit_length=bit_length,
        byte_length=byte_length,
        is_required=(attr_or_child(param, "OPTIONAL", "optional") or "").lower() not in {"true", "1", "yes"},
        is_constant=coded_value is not None or param_type.upper() in {"CODED-CONST", "NRC-CONST", "MATCHING-REQUEST-PARAM"},
    )


def param_coded_value(param: ET.Element) -> int | None:
    value = attr_or_child(param, "CODED-VALUE", "coded-value")
    if value is None:
        coded_const = first_descendant(param, "CODED-CONST")
        if coded_const is not None:
            value = attr_or_child(coded_const, "CODED-VALUE", "coded-value")
    if value is None:
        return None
    return int(value, 0)
