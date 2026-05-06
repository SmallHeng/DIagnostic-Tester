from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .config import ConfigStore
from .doip import (
    DOIP_PORT,
    PayloadType,
    decode_diagnostic_message,
    encode_alive_check_response,
    encode_diagnostic_ack,
    encode_diagnostic_message,
    encode_diagnostic_nack,
    encode_message,
    encode_routing_activation_response,
    encode_vehicle_announcement,
    parse_routing_activation_request,
    read_message,
)
from .uds import UDSDispatcher

LOGGER = logging.getLogger("diagnostic_simulator.server")


class VehicleIdentificationProtocol(asyncio.DatagramProtocol):
    def __init__(self, config_store: ConfigStore):
        self.config_store = config_store
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) < 8:
            return
        payload_type = int.from_bytes(data[2:4], "big")
        if payload_type != PayloadType.VEHICLE_IDENTIFICATION_REQUEST:
            return

        config = self.config_store.config
        payload = encode_vehicle_announcement(config.vin, config.gateway_address, config.eid, config.gid)
        response = encode_message(PayloadType.VEHICLE_ANNOUNCEMENT, payload)
        if self.transport is not None:
            self.transport.sendto(response, addr)
        LOGGER.info("Vehicle identification response sent to %s:%s", *addr)


class DoIPServer:
    def __init__(self, config_path: Path, host: str = "0.0.0.0", port: int = DOIP_PORT):
        self.config_store = ConfigStore(config_path)
        self.dispatcher = UDSDispatcher(self.config_store)
        self.host = host
        self.port = port
        self._udp_transport: asyncio.DatagramTransport | None = None
        self._tcp_server: asyncio.AbstractServer | None = None
        self._stopped: asyncio.Event | None = None

    async def start(self) -> None:
        self._stopped = asyncio.Event()
        loop = asyncio.get_running_loop()
        transport, _protocol = await loop.create_datagram_endpoint(
            lambda: VehicleIdentificationProtocol(self.config_store),
            local_addr=(self.host, self.port),
            allow_broadcast=True,
        )
        self._udp_transport = transport  # type: ignore[assignment]
        self._tcp_server = await asyncio.start_server(self._handle_client, self.host, self.port)
        sockets = ", ".join(str(sock.getsockname()) for sock in (self._tcp_server.sockets or []))
        LOGGER.info("DoIP simulator listening on %s", sockets)

    async def serve_forever(self) -> None:
        await self.start()
        if self._stopped is not None:
            await self._stopped.wait()

    async def stop(self) -> None:
        if self._tcp_server is not None:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
            self._tcp_server = None
        if self._udp_transport is not None:
            self._udp_transport.close()
            self._udp_transport = None
        if self._stopped is not None:
            self._stopped.set()
        LOGGER.info("DoIP simulator stopped")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        tester_address: int | None = None
        LOGGER.info("TCP client connected: %s", peer)
        try:
            while True:
                message = await read_message(reader)
                self.config_store.reload_if_changed()

                if message.payload_type == PayloadType.ROUTING_ACTIVATION_REQUEST:
                    tester_address, _activation_type = parse_routing_activation_request(message.payload)
                    config = self.config_store.config
                    gateway_address = config.gateway_address
                    response_code = 0x10 if self._tester_allowed(tester_address) else 0x00
                    payload = encode_routing_activation_response(tester_address, gateway_address, response_code)
                    writer.write(encode_message(PayloadType.ROUTING_ACTIVATION_RESPONSE, payload))
                    await writer.drain()
                    if response_code != 0x10:
                        LOGGER.info("Routing activation rejected for tester 0x%04X", tester_address)
                        break
                    continue

                if message.payload_type == PayloadType.ALIVE_CHECK_REQUEST:
                    source = tester_address if tester_address is not None else self.config_store.config.gateway_address
                    writer.write(encode_message(PayloadType.ALIVE_CHECK_RESPONSE, encode_alive_check_response(source)))
                    await writer.drain()
                    continue

                if message.payload_type != PayloadType.DIAGNOSTIC_MESSAGE:
                    continue

                try:
                    diagnostic = decode_diagnostic_message(message.payload)
                except ValueError:
                    writer.write(encode_message(PayloadType.DIAGNOSTIC_MESSAGE_NACK, b"\x00\x00\x00\x00\x02"))
                    await writer.drain()
                    continue
                tester_address = diagnostic.source_address
                if not self._tester_allowed(tester_address):
                    await self._send_doip_nack(writer, diagnostic.target_address, diagnostic.source_address, 0x02)
                    continue

                if self.config_store.config.diagnostic_ack:
                    await self._send_doip_ack(writer, diagnostic.target_address, diagnostic.source_address)

                async def send_pending(uds_payload: bytes) -> None:
                    await self._send_diagnostic(writer, diagnostic.target_address, diagnostic.source_address, uds_payload)

                response = await self.dispatcher.dispatch(
                    diagnostic.target_address,
                    diagnostic.uds_payload,
                    send_pending=send_pending,
                )
                if response:
                    await self._send_diagnostic(writer, diagnostic.target_address, diagnostic.source_address, response)
                if self.dispatcher.should_disconnect_after_response(diagnostic.target_address):
                    LOGGER.info(
                        "ECU 0x%04X requested reset disconnect; closing TCP client %s",
                        diagnostic.target_address,
                        peer,
                    )
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            LOGGER.info("TCP client disconnected: %s", peer)
        except Exception:
            LOGGER.exception("TCP client failed: %s", peer)
        finally:
            writer.close()
            await writer.wait_closed()

    def _tester_allowed(self, tester_address: int) -> bool:
        allowed = self.config_store.config.allowed_tester_addresses
        return not allowed or tester_address in allowed

    async def _send_doip_ack(
        self,
        writer: asyncio.StreamWriter,
        source_address: int,
        target_address: int,
        ack_code: int = 0x00,
    ) -> None:
        writer.write(encode_message(PayloadType.DIAGNOSTIC_MESSAGE_ACK, encode_diagnostic_ack(source_address, target_address, ack_code)))
        await writer.drain()

    async def _send_doip_nack(
        self,
        writer: asyncio.StreamWriter,
        source_address: int,
        target_address: int,
        nack_code: int = 0x02,
    ) -> None:
        writer.write(encode_message(PayloadType.DIAGNOSTIC_MESSAGE_NACK, encode_diagnostic_nack(source_address, target_address, nack_code)))
        await writer.drain()

    async def _send_diagnostic(
        self,
        writer: asyncio.StreamWriter,
        source_address: int,
        target_address: int,
        uds_payload: bytes,
    ) -> None:
        payload = encode_diagnostic_message(source_address, target_address, uds_payload)
        writer.write(encode_message(PayloadType.DIAGNOSTIC_MESSAGE, payload))
        await writer.drain()


async def async_main(args: argparse.Namespace) -> None:
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
    server = DoIPServer(Path(args.config), host=args.host, port=args.port)
    await server.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Industrial DoIP/UDS vehicle diagnostic ECU simulator")
    parser.add_argument("--host", default="0.0.0.0", help="IP address to bind")
    parser.add_argument("--port", type=int, default=DOIP_PORT, help="DoIP TCP/UDP port")
    parser.add_argument("--config", default="mock_data.xml", help="External XML data file")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def main() -> None:
    asyncio.run(async_main(build_parser().parse_args()))


if __name__ == "__main__":
    main()
