from __future__ import annotations

import asyncio
import ipaddress
import socket
import struct
from dataclasses import dataclass
from enum import IntEnum


DOIP_PORT = 13400
PROTOCOL_VERSION = 0x02


class PayloadType(IntEnum):
    VEHICLE_IDENTIFICATION_REQUEST = 0x0001
    VEHICLE_ANNOUNCEMENT = 0x0004
    ROUTING_ACTIVATION_REQUEST = 0x0005
    ROUTING_ACTIVATION_RESPONSE = 0x0006
    ALIVE_CHECK_REQUEST = 0x0007
    ALIVE_CHECK_RESPONSE = 0x0008
    DIAGNOSTIC_MESSAGE = 0x8001
    DIAGNOSTIC_MESSAGE_ACK = 0x8002
    DIAGNOSTIC_MESSAGE_NACK = 0x8003


class DoIPError(ValueError):
    pass


@dataclass(frozen=True)
class DoIPMessage:
    payload_type: int
    payload: bytes


@dataclass(frozen=True)
class DiagnosticMessage:
    source_address: int
    target_address: int
    uds_payload: bytes


def encode_message(payload_type: int, payload: bytes = b"") -> bytes:
    header = struct.pack(
        ">BBHI",
        PROTOCOL_VERSION,
        PROTOCOL_VERSION ^ 0xFF,
        payload_type,
        len(payload),
    )
    return header + payload


def decode_header(header: bytes) -> tuple[int, int]:
    if len(header) != 8:
        raise DoIPError("DoIP header must be exactly 8 bytes")
    version, inverse, payload_type, payload_length = struct.unpack(">BBHI", header)
    if version != PROTOCOL_VERSION or inverse != (version ^ 0xFF):
        raise DoIPError(f"Unsupported DoIP protocol version 0x{version:02X}")
    return payload_type, payload_length


async def read_message(reader: asyncio.StreamReader) -> DoIPMessage:
    header = await reader.readexactly(8)
    payload_type, payload_length = decode_header(header)
    payload = await reader.readexactly(payload_length)
    return DoIPMessage(payload_type, payload)


def encode_diagnostic_message(source_address: int, target_address: int, uds_payload: bytes) -> bytes:
    return struct.pack(">HH", source_address, target_address) + uds_payload


def encode_diagnostic_ack(source_address: int, target_address: int, ack_code: int = 0x00) -> bytes:
    return struct.pack(">HHB", source_address, target_address, ack_code)


def encode_diagnostic_nack(source_address: int, target_address: int, nack_code: int = 0x02) -> bytes:
    return struct.pack(">HHB", source_address, target_address, nack_code)


def encode_alive_check_response(source_address: int) -> bytes:
    return struct.pack(">H", source_address)


def decode_diagnostic_message(payload: bytes) -> DiagnosticMessage:
    if len(payload) < 5:
        raise DoIPError("Diagnostic message payload is too short")
    source_address, target_address = struct.unpack(">HH", payload[:4])
    return DiagnosticMessage(source_address, target_address, payload[4:])


def encode_vehicle_announcement(vin: str, logical_address: int, eid: bytes, gid: bytes) -> bytes:
    vin_bytes = vin.encode("ascii", errors="ignore")[:17].ljust(17, b"0")
    eid = eid[:6].ljust(6, b"\x00")
    gid = gid[:6].ljust(6, b"\x00")
    further_action_required = b"\x00"
    vin_gid_sync_status = b"\x00"
    return vin_bytes + struct.pack(">H", logical_address) + eid + gid + further_action_required + vin_gid_sync_status


def encode_routing_activation_response(
    tester_address: int,
    gateway_address: int,
    response_code: int = 0x10,
) -> bytes:
    return struct.pack(">HHB", tester_address, gateway_address, response_code) + b"\x00\x00\x00\x00"


def parse_routing_activation_request(payload: bytes) -> tuple[int, int]:
    if len(payload) < 3:
        raise DoIPError("Routing activation request is too short")
    tester_address = struct.unpack(">H", payload[:2])[0]
    activation_type = payload[2]
    return tester_address, activation_type


def make_broadcast_endpoint(host: str, port: int = DOIP_PORT) -> tuple[str, int]:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host, port
    if address.version == 4 and not address.is_multicast:
        return "255.255.255.255", port
    return host, port


def make_udp_socket(bind_host: str, bind_port: int, broadcast: bool = False) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if broadcast:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind((bind_host, bind_port))
    sock.setblocking(False)
    return sock
