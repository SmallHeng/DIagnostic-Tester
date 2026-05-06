import asyncio
import unittest
from pathlib import Path

from diagnostic_simulator.config import ConfigStore
from diagnostic_simulator.doip import (
    PayloadType,
    encode_diagnostic_message,
    encode_message,
    read_message,
)
from diagnostic_simulator.server import DoIPServer


XML = """<?xml version="1.0"?>
<Simulator vin="TESTVIN000000000" logical_address="0x0E00">
  <DoIP allowed_testers="0x0E80" diagnostic_ack="true" />
  <Ecus>
    <Ecu name="Gateway" address="0x1001" role="gateway" access="direct">
      <Service id="0x22">
        <Data did="0xF190">
          <Response>62 F1 90 01</Response>
        </Data>
      </Service>
    </Ecu>
  </Ecus>
</Simulator>
"""


class DoIPServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(__file__).resolve().parent / ".tmp"
        self.tmp.mkdir(exist_ok=True)
        self.config_path = self.tmp / f"{self._testMethodName}.xml"
        self.config_path.write_text(XML, encoding="utf-8")
        self.server = DoIPServer(self.config_path, host="127.0.0.1", port=0)
        await self.server.start()
        self.port = self.server._tcp_server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        await self.server.stop()
        if self.config_path.exists():
            self.config_path.unlink()

    async def _connect_and_activate(self, tester_address=0x0E80):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(encode_message(PayloadType.ROUTING_ACTIVATION_REQUEST, tester_address.to_bytes(2, "big") + b"\x00\x00\x00\x00\x00"))
        await writer.drain()
        response = await read_message(reader)
        return reader, writer, response

    async def test_diagnostic_ack_precedes_uds_response(self):
        reader, writer, activation = await self._connect_and_activate()
        self.assertEqual(activation.payload_type, PayloadType.ROUTING_ACTIVATION_RESPONSE)
        self.assertEqual(activation.payload[4], 0x10)

        payload = encode_diagnostic_message(0x0E80, 0x1001, bytes.fromhex("22 F1 90"))
        writer.write(encode_message(PayloadType.DIAGNOSTIC_MESSAGE, payload))
        await writer.drain()

        ack = await read_message(reader)
        uds = await read_message(reader)

        self.assertEqual(ack.payload_type, PayloadType.DIAGNOSTIC_MESSAGE_ACK)
        self.assertEqual(ack.payload, bytes.fromhex("10 01 0E 80 00"))
        self.assertEqual(uds.payload_type, PayloadType.DIAGNOSTIC_MESSAGE)
        self.assertEqual(uds.payload, bytes.fromhex("10 01 0E 80 62 F1 90 01"))
        writer.close()
        await writer.wait_closed()

    async def test_routing_activation_rejects_disallowed_tester(self):
        reader, writer, activation = await self._connect_and_activate(tester_address=0x0E81)

        self.assertEqual(activation.payload_type, PayloadType.ROUTING_ACTIVATION_RESPONSE)
        self.assertEqual(activation.payload[4], 0x00)
        writer.close()
        await writer.wait_closed()

    async def test_alive_check_response(self):
        reader, writer, activation = await self._connect_and_activate()
        self.assertEqual(activation.payload[4], 0x10)

        writer.write(encode_message(PayloadType.ALIVE_CHECK_REQUEST))
        await writer.drain()
        response = await read_message(reader)

        self.assertEqual(response.payload_type, PayloadType.ALIVE_CHECK_RESPONSE)
        self.assertEqual(response.payload, bytes.fromhex("0E 80"))
        writer.close()
        await writer.wait_closed()


if __name__ == "__main__":
    unittest.main()
