from __future__ import annotations


NRC_DESCRIPTIONS: dict[int, str] = {
    0x10: "General Reject",
    0x11: "Service Not Supported",
    0x12: "Sub-Function Not Supported",
    0x13: "Incorrect Message Length Or Invalid Format",
    0x21: "Busy Repeat Request",
    0x22: "Conditions Not Correct",
    0x24: "Request Sequence Error",
    0x31: "Request Out Of Range",
    0x33: "Security Access Denied",
    0x35: "Invalid Key",
    0x36: "Exceeded Number Of Attempts",
    0x37: "Required Time Delay Not Expired",
    0x72: "General Programming Failure",
    0x78: "Response Pending",
}


def describe_nrc(code: int | bytes) -> str:
    if isinstance(code, bytes):
        if len(code) >= 3 and code[0] == 0x7F:
            code = code[2]
        elif code:
            code = code[-1]
        else:
            return "Unknown NRC"
    return NRC_DESCRIPTIONS.get(int(code), f"Unknown NRC 0x{int(code):02X}")


def decode_negative_response(payload: bytes) -> tuple[int, int, str] | None:
    if len(payload) < 3 or payload[0] != 0x7F:
        return None
    service_id = payload[1]
    nrc = payload[2]
    return service_id, nrc, describe_nrc(nrc)
