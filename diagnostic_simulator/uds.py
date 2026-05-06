from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .config import ConfigStore, DataRule, DtcRecord, EcuConfig, SecurityLevel, ServiceRule

PendingSender = Callable[[bytes], Awaitable[None]]

NRC_SERVICE_NOT_SUPPORTED = 0x11
NRC_SUBFUNCTION_NOT_SUPPORTED = 0x12
NRC_INCORRECT_MESSAGE_LENGTH = 0x13
NRC_BUSY_REPEAT_REQUEST = 0x21
NRC_CONDITIONS_NOT_CORRECT = 0x22
NRC_REQUEST_SEQUENCE_ERROR = 0x24
NRC_REQUEST_OUT_OF_RANGE = 0x31
NRC_SECURITY_ACCESS_DENIED = 0x33
NRC_INVALID_KEY = 0x35
NRC_EXCEEDED_NUMBER_OF_ATTEMPTS = 0x36
NRC_REQUIRED_TIME_DELAY_NOT_EXPIRED = 0x37
NRC_UPLOAD_DOWNLOAD_NOT_ACCEPTED = 0x70
NRC_TRANSFER_DATA_SUSPENDED = 0x71
NRC_WRONG_BLOCK_SEQUENCE_COUNTER = 0x73
NRC_SERVICE_NOT_SUPPORTED_IN_ACTIVE_SESSION = 0x7F


def negative_response(sid: int, code: int) -> bytes:
    return bytes([0x7F, sid, code])


@dataclass
class EcuRuntimeState:
    session: int = 0x01
    authenticated: bool = False
    counters: defaultdict[tuple[int, int | bytes], int] = field(default_factory=lambda: defaultdict(int))
    s3_task: asyncio.Task[None] | None = None
    dtcs: dict[int, DtcRecord] = field(default_factory=dict)
    dtc_source: tuple[DtcRecord, ...] = ()
    reboot_until: float = 0.0
    disconnect_after_response: bool = False
    unlocked_security_levels: set[str] = field(default_factory=set)
    security_attempts: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))
    security_lock_until: defaultdict[str, float] = field(default_factory=lambda: defaultdict(float))
    download_active: bool = False
    download_address: int = 0
    download_size: int = 0
    download_received: int = 0
    expected_block_counter: int = 1
    last_block_counter: int | None = None
    last_block_response: bytes = b""


class UDSDispatcher:
    def __init__(self, config_store: ConfigStore):
        self.config_store = config_store
        self.states: dict[int, EcuRuntimeState] = defaultdict(EcuRuntimeState)

    async def dispatch(
        self,
        ecu_address: int,
        request: bytes,
        send_pending: PendingSender | None = None,
    ) -> bytes:
        config = self.config_store.config
        ecu = config.ecus.get(ecu_address)
        if ecu is None:
            sid = request[0] if request else 0x00
            return negative_response(sid, NRC_REQUEST_OUT_OF_RANGE)
        if not request:
            return negative_response(0x00, NRC_INCORRECT_MESSAGE_LENGTH)

        sid = request[0]
        if not self._is_route_allowed(config.ecus, ecu):
            return negative_response(sid, NRC_REQUEST_OUT_OF_RANGE)

        state = self.states[ecu_address]
        self._ensure_dtc_state(ecu, state)
        if self._is_rebooting(state):
            return negative_response(sid, NRC_BUSY_REPEAT_REQUEST)

        service = ecu.services.get(sid)
        if service is None and sid not in {0x10, 0x3E, 0x11, 0x14, 0x19, 0x27, 0x34, 0x36, 0x37}:
            return negative_response(sid, NRC_SERVICE_NOT_SUPPORTED)

        if service is not None:
            denied = self._permission_denied(sid, service, state)
            if denied is not None:
                return denied

        if sid == 0x10:
            response = self._diagnostic_session_control(ecu, state, request)
        elif sid == 0x3E:
            response = self._tester_present(request)
        elif sid == 0x27:
            response = self._security_access(ecu, state, request)
        elif sid == 0x34:
            response = self._request_download(ecu, state, request)
        elif sid == 0x36:
            response = self._transfer_data(ecu, state, request)
        elif sid == 0x37:
            response = self._request_transfer_exit(ecu, state, request)
        elif sid == 0x11:
            response = await self._ecu_reset(ecu, state, request, send_pending)
        elif sid == 0x14:
            response = self._clear_diagnostic_information(state, request)
        elif sid == 0x19:
            response = await self._read_dtc_information(ecu_address, state, request, send_pending)
        elif service and service.handler == "mock_auth":
            response = self._mock_auth(state, request)
        elif service and service.handler == "dynamic_echo":
            response = self._dynamic_echo(request)
        else:
            response = await self._configured_response(ecu_address, state, request, send_pending)

        self._reset_s3_watchdog(ecu, state)
        return response

    def should_disconnect_after_response(self, ecu_address: int) -> bool:
        state = self.states.get(ecu_address)
        if state is None or not state.disconnect_after_response:
            return False
        state.disconnect_after_response = False
        return True

    def _diagnostic_session_control(self, ecu: EcuConfig, state: EcuRuntimeState, request: bytes) -> bytes:
        if len(request) != 2:
            return negative_response(request[0], NRC_INCORRECT_MESSAGE_LENGTH)
        subfunction = request[1] & 0x7F
        if subfunction not in {0x01, 0x02, 0x03}:
            return negative_response(request[0], NRC_SUBFUNCTION_NOT_SUPPORTED)
        state.session = subfunction
        self._reset_s3_watchdog(ecu, state)
        # P2=50ms, P2*=5000ms encoded per ISO 14229 timing bytes.
        return bytes([0x50, subfunction, 0x00, 0x32, 0x01, 0xF4])

    def _tester_present(self, request: bytes) -> bytes:
        if len(request) != 2:
            return negative_response(request[0], NRC_INCORRECT_MESSAGE_LENGTH)
        subfunction = request[1] & 0x7F
        if subfunction != 0x00:
            return negative_response(request[0], NRC_SUBFUNCTION_NOT_SUPPORTED)
        suppress_positive = bool(request[1] & 0x80)
        if suppress_positive:
            return b""
        return bytes([0x7E, request[1] & 0x7F])

    def _mock_auth(self, state: EcuRuntimeState, request: bytes) -> bytes:
        if len(request) < 2:
            return negative_response(request[0], NRC_INCORRECT_MESSAGE_LENGTH)
        subfunction = request[1]
        if subfunction in {0x01, 0x02}:
            return bytes([0x69, subfunction]) + os.urandom(16)
        if subfunction == 0x03:
            state.authenticated = True
            state.unlocked_security_levels.add("auth")
            return b"\x69\x03"
        return negative_response(request[0], NRC_SUBFUNCTION_NOT_SUPPORTED)

    def _security_access(self, ecu: EcuConfig, state: EcuRuntimeState, request: bytes) -> bytes:
        if len(request) < 2:
            return negative_response(0x27, NRC_INCORRECT_MESSAGE_LENGTH)
        subfunction = request[1]
        level = ecu.security_levels.get(subfunction)
        if level is None:
            return negative_response(0x27, NRC_SUBFUNCTION_NOT_SUPPORTED)
        now = asyncio.get_running_loop().time()
        if state.security_lock_until[level.name] > now:
            return negative_response(0x27, NRC_REQUIRED_TIME_DELAY_NOT_EXPIRED)
        if subfunction == level.request_seed:
            return bytes([0x67, subfunction]) + level.seed
        if subfunction == level.send_key:
            return self._security_key_response(state, request, level, now)
        return negative_response(0x27, NRC_SUBFUNCTION_NOT_SUPPORTED)

    def _security_key_response(
        self,
        state: EcuRuntimeState,
        request: bytes,
        level: SecurityLevel,
        now: float,
    ) -> bytes:
        if len(request) < 2 + len(level.key):
            return negative_response(0x27, NRC_INCORRECT_MESSAGE_LENGTH)
        if request[2:] == level.key:
            state.unlocked_security_levels.add(level.name)
            state.security_attempts[level.name] = 0
            state.security_lock_until[level.name] = 0.0
            return bytes([0x67, level.send_key])

        state.security_attempts[level.name] += 1
        if state.security_attempts[level.name] >= level.max_attempts:
            state.security_lock_until[level.name] = now + level.lock_time
            return negative_response(0x27, NRC_EXCEEDED_NUMBER_OF_ATTEMPTS)
        return negative_response(0x27, NRC_INVALID_KEY)

    def _dynamic_echo(self, request: bytes) -> bytes:
        if len(request) < 2:
            return negative_response(request[0], NRC_INCORRECT_MESSAGE_LENGTH)
        return bytes([request[0] + 0x40, request[1]])

    def _request_download(self, ecu: EcuConfig, state: EcuRuntimeState, request: bytes) -> bytes:
        denied = self._download_permission_denied(0x34, ecu, state)
        if denied is not None:
            return denied
        if len(request) < 5:
            return negative_response(0x34, NRC_INCORRECT_MESSAGE_LENGTH)

        address_length_format = request[2]
        address_length = address_length_format & 0x0F
        size_length = (address_length_format >> 4) & 0x0F
        expected_length = 3 + address_length + size_length
        if address_length == 0 or size_length == 0 or len(request) != expected_length:
            return negative_response(0x34, NRC_INCORRECT_MESSAGE_LENGTH)

        memory_address = int.from_bytes(request[3 : 3 + address_length], "big")
        memory_size = int.from_bytes(request[3 + address_length : expected_length], "big")
        if memory_size <= 0:
            return negative_response(0x34, NRC_REQUEST_OUT_OF_RANGE)
        if memory_address < ecu.download.start_address:
            return negative_response(0x34, NRC_REQUEST_OUT_OF_RANGE)
        if memory_address + memory_size - 1 > ecu.download.end_address:
            return negative_response(0x34, NRC_REQUEST_OUT_OF_RANGE)

        state.download_active = True
        state.download_address = memory_address
        state.download_size = memory_size
        state.download_received = 0
        state.expected_block_counter = 1
        state.last_block_counter = None
        state.last_block_response = b""
        max_block_length = max(ecu.download.max_block_length, 1)
        return bytes([0x74, 0x20]) + max_block_length.to_bytes(2, "big")

    def _transfer_data(self, ecu: EcuConfig, state: EcuRuntimeState, request: bytes) -> bytes:
        denied = self._download_permission_denied(0x36, ecu, state)
        if denied is not None:
            return denied
        if len(request) < 2:
            return negative_response(0x36, NRC_INCORRECT_MESSAGE_LENGTH)
        if not state.download_active:
            service = ecu.services.get(0x36)
            if service and service.handler == "dynamic_echo":
                return self._dynamic_echo(request)
            return negative_response(0x36, NRC_UPLOAD_DOWNLOAD_NOT_ACCEPTED)

        block_counter = request[1]
        data = request[2:]
        if block_counter == state.last_block_counter:
            return state.last_block_response
        if block_counter != state.expected_block_counter:
            return negative_response(0x36, NRC_WRONG_BLOCK_SEQUENCE_COUNTER)
        if len(data) > ecu.download.max_block_length:
            return negative_response(0x36, NRC_REQUEST_OUT_OF_RANGE)
        if state.download_received + len(data) > state.download_size:
            return negative_response(0x36, NRC_TRANSFER_DATA_SUSPENDED)

        state.download_received += len(data)
        response = bytes([0x76, block_counter])
        state.last_block_counter = block_counter
        state.last_block_response = response
        state.expected_block_counter = (block_counter + 1) & 0xFF
        return response

    def _request_transfer_exit(self, ecu: EcuConfig, state: EcuRuntimeState, request: bytes) -> bytes:
        denied = self._download_permission_denied(0x37, ecu, state)
        if denied is not None:
            return denied
        if not state.download_active:
            return negative_response(0x37, NRC_UPLOAD_DOWNLOAD_NOT_ACCEPTED)
        if state.download_received != state.download_size:
            return negative_response(0x37, NRC_TRANSFER_DATA_SUSPENDED)
        state.download_active = False
        return b"\x77"

    async def _read_dtc_information(
        self,
        ecu_address: int,
        state: EcuRuntimeState,
        request: bytes,
        send_pending: PendingSender | None,
    ) -> bytes:
        override = await self._configured_response_or_none(ecu_address, state, request, send_pending)
        if override is not None:
            return override
        if len(request) < 2:
            return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)

        subfunction = request[1]
        all_dtcs = list(state.dtcs.values())
        active_dtcs = [dtc for dtc in all_dtcs if dtc.status != 0]
        status_availability_mask = 0xFF

        if subfunction == 0x01:
            if len(request) != 3:
                return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)
            count = len(self._filter_by_status(active_dtcs, request[2]))
            return bytes([0x59, subfunction, status_availability_mask, 0x01]) + count.to_bytes(2, "big")

        if subfunction == 0x02:
            if len(request) != 3:
                return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)
            return bytes([0x59, subfunction, status_availability_mask]) + self._encode_dtc_status_list(
                self._filter_by_status(active_dtcs, request[2])
            )

        if subfunction == 0x04:
            if len(request) != 6:
                return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)
            dtc = state.dtcs.get(int.from_bytes(request[2:5], "big"))
            if dtc is None or dtc.status == 0:
                return negative_response(0x19, NRC_REQUEST_OUT_OF_RANGE)
            record_number = request[5]
            if not dtc.snapshot or record_number not in {dtc.snapshot_record, 0xFF}:
                return negative_response(0x19, NRC_REQUEST_OUT_OF_RANGE)
            return bytes([0x59, subfunction]) + self._dtc_bytes(dtc.code) + bytes([dtc.status, record_number]) + dtc.snapshot

        if subfunction == 0x06:
            if len(request) != 6:
                return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)
            dtc = state.dtcs.get(int.from_bytes(request[2:5], "big"))
            if dtc is None or dtc.status == 0:
                return negative_response(0x19, NRC_REQUEST_OUT_OF_RANGE)
            record_number = request[5]
            if not dtc.extended_data or record_number not in {dtc.extended_data_record, 0xFF}:
                return negative_response(0x19, NRC_REQUEST_OUT_OF_RANGE)
            return bytes([0x59, subfunction]) + self._dtc_bytes(dtc.code) + bytes([dtc.status, record_number]) + dtc.extended_data

        if subfunction == 0x07:
            if len(request) != 4:
                return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)
            count = len(self._filter_by_severity_and_status(active_dtcs, request[2], request[3]))
            return bytes([0x59, subfunction, status_availability_mask, 0x01]) + count.to_bytes(2, "big")

        if subfunction == 0x08:
            if len(request) != 5:
                return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)
            dtc = state.dtcs.get(int.from_bytes(request[2:5], "big"))
            if dtc is None or dtc.status == 0:
                return negative_response(0x19, NRC_REQUEST_OUT_OF_RANGE)
            return (
                bytes([0x59, subfunction, dtc.severity, dtc.functional_unit])
                + self._dtc_bytes(dtc.code)
                + bytes([dtc.status])
            )

        if subfunction == 0x09:
            if len(request) != 4:
                return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)
            return bytes([0x59, subfunction, status_availability_mask]) + self._encode_dtc_severity_status_list(
                self._filter_by_severity_and_status(active_dtcs, request[2], request[3])
            )

        if subfunction == 0x0A:
            if len(request) != 2:
                return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)
            return bytes([0x59, subfunction]) + self._encode_dtc_status_list(all_dtcs)

        if subfunction == 0x0F:
            if len(request) != 3:
                return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)
            mirror_dtcs = [dtc for dtc in active_dtcs if dtc.memory == "mirror"]
            return bytes([0x59, subfunction, status_availability_mask]) + self._encode_dtc_status_list(
                self._filter_by_status(mirror_dtcs, request[2])
            )

        if subfunction == 0x11:
            if len(request) != 3:
                return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)
            mirror_dtcs = [dtc for dtc in active_dtcs if dtc.memory == "mirror"]
            count = len(self._filter_by_status(mirror_dtcs, request[2]))
            return bytes([0x59, subfunction, status_availability_mask, 0x01]) + count.to_bytes(2, "big")

        if subfunction == 0x12:
            if len(request) != 3:
                return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)
            obd_dtcs = [dtc for dtc in active_dtcs if dtc.memory == "obd"]
            count = len(self._filter_by_status(obd_dtcs, request[2]))
            return bytes([0x59, subfunction, status_availability_mask, 0x01]) + count.to_bytes(2, "big")

        if subfunction == 0x14:
            if len(request) != 2:
                return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)
            return bytes([0x59, subfunction]) + b"".join(
                self._dtc_bytes(dtc.code) + bytes([dtc.fault_detection_counter]) for dtc in active_dtcs
            )

        if subfunction == 0x15:
            if len(request) != 2:
                return negative_response(0x19, NRC_INCORRECT_MESSAGE_LENGTH)
            permanent_dtcs = [dtc for dtc in active_dtcs if dtc.permanent]
            return bytes([0x59, subfunction]) + self._encode_dtc_status_list(permanent_dtcs)

        return negative_response(0x19, NRC_SUBFUNCTION_NOT_SUPPORTED)

    def _clear_diagnostic_information(self, state: EcuRuntimeState, request: bytes) -> bytes:
        if len(request) != 4:
            return negative_response(0x14, NRC_INCORRECT_MESSAGE_LENGTH)
        group = int.from_bytes(request[1:4], "big")
        for code, dtc in list(state.dtcs.items()):
            if self._dtc_matches_group(code, group) and dtc.clearable:
                state.dtcs[code] = self._copy_dtc(
                    dtc,
                    status=dtc.clear_status,
                    fault_detection_counter=dtc.clear_fault_detection_counter,
                )
        return b"\x54"

    async def _ecu_reset(
        self,
        ecu: EcuConfig,
        state: EcuRuntimeState,
        request: bytes,
        send_pending: PendingSender | None,
    ) -> bytes:
        service = self.config_store.config.ecus[ecu.address].services.get(0x11)
        override = await self._configured_response_or_none(ecu.address, state, request, send_pending)
        if override is not None:
            if override.startswith(b"\x7F\x11"):
                return override
            self._apply_ecu_reset(ecu, state, service)
            return override
        if len(request) != 2:
            return negative_response(0x11, NRC_INCORRECT_MESSAGE_LENGTH)
        subfunction = request[1] & 0x7F
        supported_reset_types = service.supported_reset_types if service is not None else ()
        if supported_reset_types:
            if subfunction not in supported_reset_types:
                return negative_response(0x11, NRC_SUBFUNCTION_NOT_SUPPORTED)
        elif subfunction not in {0x01, 0x02, 0x03}:
            return negative_response(0x11, NRC_SUBFUNCTION_NOT_SUPPORTED)
        self._apply_ecu_reset(ecu, state, service)
        return bytes([0x51, subfunction])

    async def _configured_response(
        self,
        ecu_address: int,
        state: EcuRuntimeState,
        request: bytes,
        send_pending: PendingSender | None,
    ) -> bytes:
        sid = request[0]
        service = self.config_store.config.ecus[ecu_address].services.get(sid)
        if service is None:
            return negative_response(sid, NRC_SERVICE_NOT_SUPPORTED)

        rule = self._match_rule(service.data_rules, request)
        if rule is None:
            return negative_response(sid, NRC_REQUEST_OUT_OF_RANGE)

        denied = self._permission_denied(sid, rule, state)
        if denied is not None:
            return denied

        if rule.simulate_pending and send_pending is not None:
            await self._simulate_pending(sid, rule, send_pending)

        return self._select_response(state, sid, rule)

    def _match_rule(self, rules: tuple[DataRule, ...], request: bytes) -> DataRule | None:
        for rule in rules:
            if rule.request and request == rule.request:
                return rule
            if rule.did is not None and len(request) >= 3:
                did = int.from_bytes(request[1:3], "big")
                if did == rule.did:
                    return rule
        return None

    async def _configured_response_or_none(
        self,
        ecu_address: int,
        state: EcuRuntimeState,
        request: bytes,
        send_pending: PendingSender | None,
    ) -> bytes | None:
        sid = request[0] if request else 0x00
        service = self.config_store.config.ecus[ecu_address].services.get(sid)
        if service is None:
            return None
        rule = self._match_rule(service.data_rules, request)
        if rule is None:
            return None
        denied = self._permission_denied(sid, rule, state)
        if denied is not None:
            return denied
        if rule.simulate_pending and send_pending is not None:
            await self._simulate_pending(sid, rule, send_pending)
        return self._select_response(state, sid, rule)

    def _select_response(self, state: EcuRuntimeState, sid: int, rule: DataRule) -> bytes:
        if not rule.responses:
            return negative_response(sid, NRC_REQUEST_OUT_OF_RANGE)
        key: tuple[int, int | bytes] = (sid, rule.did if rule.did is not None else rule.request)
        if rule.response_mode == "sequential":
            index = state.counters[key] % len(rule.responses)
            state.counters[key] += 1
            return rule.responses[index]
        return rule.responses[0]

    def _ensure_dtc_state(self, ecu: EcuConfig, state: EcuRuntimeState) -> None:
        if state.dtc_source == ecu.dtcs:
            return
        state.dtcs = {dtc.code: dtc for dtc in ecu.dtcs}
        state.dtc_source = ecu.dtcs

    def _reset_runtime_state(self, ecu: EcuConfig, state: EcuRuntimeState, restore_dtcs: bool = True) -> None:
        if state.s3_task is not None:
            state.s3_task.cancel()
            state.s3_task = None
        state.session = 0x01
        state.authenticated = False
        state.counters.clear()
        if restore_dtcs:
            state.dtcs = {dtc.code: dtc for dtc in ecu.dtcs}
            state.dtc_source = ecu.dtcs
        state.unlocked_security_levels.clear()
        state.security_attempts.clear()
        state.security_lock_until.clear()
        state.download_active = False
        state.download_address = 0
        state.download_size = 0
        state.download_received = 0
        state.expected_block_counter = 1
        state.last_block_counter = None
        state.last_block_response = b""
        state.reboot_until = 0.0
        state.disconnect_after_response = False

    def _apply_ecu_reset(self, ecu: EcuConfig, state: EcuRuntimeState, service) -> None:
        restore_dtcs = service.restore_dtcs_on_reset if service is not None else True
        self._reset_runtime_state(ecu, state, restore_dtcs=restore_dtcs)
        reset_behavior = service.reset_behavior if service is not None else "state_only"
        reset_delay = service.reset_delay if service is not None else 0.0
        if reset_delay > 0:
            state.reboot_until = asyncio.get_running_loop().time() + reset_delay
        if reset_behavior == "disconnect":
            state.disconnect_after_response = True

    def _is_rebooting(self, state: EcuRuntimeState) -> bool:
        return state.reboot_until > asyncio.get_running_loop().time()

    def _is_route_allowed(self, ecus: dict[int, EcuConfig], ecu: EcuConfig) -> bool:
        if ecu.access == "direct":
            return True
        if ecu.access != "proxied":
            return False
        if ecu.gateway_address is None:
            return False
        gateway = ecus.get(ecu.gateway_address)
        return gateway is not None and gateway.role == "gateway"

    def _permission_denied(
        self,
        sid: int,
        rule: ServiceRule | DataRule,
        state: EcuRuntimeState,
    ) -> bytes | None:
        if rule.required_sessions and state.session not in rule.required_sessions:
            return negative_response(sid, NRC_SERVICE_NOT_SUPPORTED_IN_ACTIVE_SESSION)
        if rule.required_security and rule.required_security not in state.unlocked_security_levels:
            return negative_response(sid, NRC_SECURITY_ACCESS_DENIED)
        return None

    def _download_permission_denied(self, sid: int, ecu: EcuConfig, state: EcuRuntimeState) -> bytes | None:
        if ecu.download.required_sessions and state.session not in ecu.download.required_sessions:
            return negative_response(sid, NRC_SERVICE_NOT_SUPPORTED_IN_ACTIVE_SESSION)
        if ecu.download.required_security and ecu.download.required_security not in state.unlocked_security_levels:
            return negative_response(sid, NRC_SECURITY_ACCESS_DENIED)
        return None

    def _filter_by_status(self, dtcs: list[DtcRecord], status_mask: int) -> list[DtcRecord]:
        return [dtc for dtc in dtcs if dtc.status & status_mask]

    def _filter_by_severity_and_status(
        self,
        dtcs: list[DtcRecord],
        severity_mask: int,
        status_mask: int,
    ) -> list[DtcRecord]:
        return [dtc for dtc in dtcs if dtc.severity & severity_mask and dtc.status & status_mask]

    def _encode_dtc_status_list(self, dtcs: list[DtcRecord]) -> bytes:
        return b"".join(self._dtc_bytes(dtc.code) + bytes([dtc.status]) for dtc in dtcs)

    def _encode_dtc_severity_status_list(self, dtcs: list[DtcRecord]) -> bytes:
        return b"".join(
            bytes([dtc.severity, dtc.functional_unit]) + self._dtc_bytes(dtc.code) + bytes([dtc.status])
            for dtc in dtcs
        )

    def _dtc_bytes(self, code: int) -> bytes:
        return (code & 0xFFFFFF).to_bytes(3, "big")

    def _dtc_matches_group(self, code: int, group: int) -> bool:
        if group == 0xFFFFFF:
            return True
        if group <= 0xFF:
            return (code >> 16) == group
        if group <= 0xFFFF:
            return (code >> 8) == group
        return code == group

    def _copy_dtc(
        self,
        dtc: DtcRecord,
        *,
        status: int | None = None,
        fault_detection_counter: int | None = None,
    ) -> DtcRecord:
        return DtcRecord(
            code=dtc.code,
            status=dtc.status if status is None else status & 0xFF,
            severity=dtc.severity,
            functional_unit=dtc.functional_unit,
            fault_detection_counter=(
                dtc.fault_detection_counter
                if fault_detection_counter is None
                else fault_detection_counter & 0xFF
            ),
            snapshot=dtc.snapshot,
            extended_data=dtc.extended_data,
            memory=dtc.memory,
            permanent=dtc.permanent,
            clearable=dtc.clearable,
            clear_status=dtc.clear_status,
            clear_fault_detection_counter=dtc.clear_fault_detection_counter,
            snapshot_record=dtc.snapshot_record,
            extended_data_record=dtc.extended_data_record,
        )

    async def _simulate_pending(self, sid: int, rule: DataRule, send_pending: PendingSender) -> None:
        elapsed = 0.0
        interval = max(rule.pending_interval, 0.05)
        while elapsed < rule.total_delay:
            await asyncio.sleep(min(interval, rule.total_delay - elapsed))
            elapsed += interval
            if elapsed < rule.total_delay:
                await send_pending(negative_response(sid, 0x78))

    def _reset_s3_watchdog(self, ecu: EcuConfig, state: EcuRuntimeState) -> None:
        if state.s3_task is not None:
            state.s3_task.cancel()
            state.s3_task = None
        if state.session != 0x01:
            state.s3_task = asyncio.create_task(self._s3_timeout(ecu, state))

    async def _s3_timeout(self, ecu: EcuConfig, state: EcuRuntimeState) -> None:
        try:
            await asyncio.sleep(ecu.s3_timeout)
            state.session = 0x01
            state.authenticated = False
        except asyncio.CancelledError:
            return
