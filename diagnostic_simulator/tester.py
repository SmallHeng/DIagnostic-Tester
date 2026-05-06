from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import socket
import struct
from collections.abc import Callable

from .doip import (
    DOIP_PORT,
    PayloadType,
    decode_diagnostic_message,
    encode_diagnostic_message,
    encode_message,
    make_udp_socket,
    read_message,
)

LOGGER = logging.getLogger("diagnostic_simulator.tester")


class TesterClient:
    def __init__(
        self,
        tester_address: int = 0x0E80,
        target_address: int = 0x1001,
        port: int = DOIP_PORT,
        p3_client_time: float = 2.0,
        heartbeat_tx_callback: Callable[[bytes], None] | None = None,
        heartbeat_rx_callback: Callable[[bytes], None] | None = None,
    ):
        self.tester_address = tester_address
        self.target_address = target_address
        self.port = port
        self.p3_client_time = p3_client_time
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.rx_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.lock = asyncio.Lock()
        self.receiver_task: asyncio.Task[None] | None = None
        self.heartbeat_task: asyncio.Task[None] | None = None
        self.disconnected = True
        self.heartbeat_tx_callback = heartbeat_tx_callback
        self.heartbeat_rx_callback = heartbeat_rx_callback

    async def discover(self, timeout: float = 2.0, broadcast_host: str = "255.255.255.255") -> tuple[str, int]:
        loop = asyncio.get_running_loop()
        sock = make_udp_socket("0.0.0.0", 0, broadcast=True)
        try:
            request = encode_message(PayloadType.VEHICLE_IDENTIFICATION_REQUEST)
            await loop.sock_sendto(sock, request, (broadcast_host, self.port))
            data, addr = await asyncio.wait_for(loop.sock_recvfrom(sock, 4096), timeout)
            if int.from_bytes(data[2:4], "big") != PayloadType.VEHICLE_ANNOUNCEMENT:
                raise RuntimeError("Unexpected DoIP discovery response")
            return addr[0], addr[1]
        finally:
            sock.close()

    async def connect(self, host: str) -> None:
        self.disconnected = False
        self.rx_queue = asyncio.Queue()
        self.reader, self.writer = await asyncio.open_connection(host, self.port)
        request_payload = struct.pack(">HBI", self.tester_address, 0x00, 0x00000000)
        self.writer.write(encode_message(PayloadType.ROUTING_ACTIVATION_REQUEST, request_payload))
        await self.writer.drain()
        response = await read_message(self.reader)
        if response.payload_type != PayloadType.ROUTING_ACTIVATION_RESPONSE or response.payload[4] != 0x10:
            raise RuntimeError("Routing activation rejected")
        self.receiver_task = asyncio.create_task(self._receive_loop())
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def close(self) -> None:
        self.disconnected = True
        for task in (self.heartbeat_task, self.receiver_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if self.writer is not None:
            self.writer.close()
            await self.writer.wait_closed()

    async def send_uds(self, uds_payload: bytes, target_address: int | None = None) -> bytes:
        if self.disconnected:
            raise RuntimeError("Tester is disconnected; reconnect before sending")
        target = self.target_address if target_address is None else target_address
        async with self.lock:
            await self._write_diagnostic(uds_payload, target)
            return await self._wait_response()

    async def _write_diagnostic(self, uds_payload: bytes, target_address: int) -> None:
        if self.writer is None or self.writer.is_closing():
            self.disconnected = True
            raise RuntimeError("Tester is not connected")
        payload = encode_diagnostic_message(self.tester_address, target_address, uds_payload)
        self.writer.write(encode_message(PayloadType.DIAGNOSTIC_MESSAGE, payload))
        await self.writer.drain()

    async def _wait_response(self) -> bytes:
        response = await asyncio.wait_for(self.rx_queue.get(), timeout=0.1)
        if response is None:
            raise RuntimeError("Simulator closed the connection; reconnect before sending more requests")
        if len(response) >= 3 and response[0] == 0x7F and response[2] == 0x78:
            while True:
                response = await asyncio.wait_for(self.rx_queue.get(), timeout=5.0)
                if response is None:
                    raise RuntimeError("Simulator closed the connection while waiting for final response")
                if not (len(response) >= 3 and response[0] == 0x7F and response[2] == 0x78):
                    return response
        return response

    async def _receive_loop(self) -> None:
        if self.reader is None:
            return
        try:
            while True:
                message = await read_message(self.reader)
                if message.payload_type != PayloadType.DIAGNOSTIC_MESSAGE:
                    continue
                diagnostic = decode_diagnostic_message(message.payload)
                await self.rx_queue.put(diagnostic.uds_payload)
        except (asyncio.IncompleteReadError, ConnectionError):
            self.disconnected = True
            await self.rx_queue.put(None)

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self.p3_client_time)
            async with self.lock:
                if self.disconnected:
                    return
                try:
                    heartbeat = b"\x3E\x80"
                    await self._write_diagnostic(heartbeat, self.target_address)
                    if self.heartbeat_tx_callback is not None:
                        self.heartbeat_tx_callback(heartbeat)
                    await self._consume_heartbeat_response()
                except (ConnectionError, RuntimeError):
                    self.disconnected = True
                    return

    async def _consume_heartbeat_response(self) -> None:
        try:
            response = await asyncio.wait_for(self.rx_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return
        if response is None:
            self.disconnected = True
            return
        if self.heartbeat_rx_callback is not None:
            self.heartbeat_rx_callback(response)


async def async_input(prompt: str) -> str:
    try:
        import aioconsole  # type: ignore

        return await aioconsole.ainput(prompt)
    except ImportError:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, input, prompt)


def parse_hex_command(line: str) -> bytes:
    cleaned = line.strip().replace("0x", "").replace("0X", "").replace(" ", "")
    if not cleaned:
        return b""
    if len(cleaned) % 2:
        raise ValueError("Hex command must contain whole bytes")
    return bytes.fromhex(cleaned)


async def repl(client: TesterClient) -> None:
    while True:
        line = (await async_input("uds> ")).strip()
        if line.lower() in {"quit", "exit", "q"}:
            return
        try:
            request = parse_hex_command(line)
            if not request:
                continue
            response = await client.send_uds(request)
            print(response.hex(" ").upper())
        except Exception as exc:
            print(f"ERROR: {exc}")


async def async_main(args: argparse.Namespace) -> None:
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
    client = TesterClient(
        tester_address=int(args.source, 0),
        target_address=int(args.target, 0),
        port=args.port,
        p3_client_time=args.p3,
    )
    host = args.host
    if host is None:
        host, _ = await client.discover(timeout=args.discovery_timeout)
        LOGGER.info("Discovered simulator at %s", host)
    await client.connect(host)
    try:
        await repl(client)
    finally:
        await client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lightweight DoIP/UDS tester CLI")
    parser.add_argument("--host", help="Simulator host. If omitted, UDP discovery is used.")
    parser.add_argument("--port", type=int, default=DOIP_PORT)
    parser.add_argument("--source", default="0x0E80", help="Tester logical address")
    parser.add_argument("--target", default="0x1001", help="ECU logical address")
    parser.add_argument("--p3", type=float, default=2.0, help="Tester Present interval in seconds")
    parser.add_argument("--discovery-timeout", type=float, default=2.0)
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def main() -> None:
    asyncio.run(async_main(build_parser().parse_args()))


if __name__ == "__main__":
    main()
