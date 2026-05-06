import asyncio
import contextlib
import unittest

from diagnostic_simulator.tester import TesterClient


class TesterClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeat_callback_is_called_after_3e80_send(self):
        sent = []
        callback_payloads = []
        event = asyncio.Event()
        client = TesterClient(p3_client_time=0.01, heartbeat_tx_callback=lambda payload: (callback_payloads.append(payload), event.set()))
        client.disconnected = False

        async def fake_write(payload, target):
            sent.append((payload, target))

        client._write_diagnostic = fake_write
        task = asyncio.create_task(client._heartbeat_loop())
        try:
            await asyncio.wait_for(event.wait(), timeout=1.0)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self.assertEqual(sent[0][0], bytes.fromhex("3E 80"))
        self.assertEqual(callback_payloads[0], bytes.fromhex("3E 80"))

    async def test_heartbeat_negative_response_is_not_left_for_manual_request(self):
        rx_payloads = []
        event = asyncio.Event()
        client = TesterClient(
            p3_client_time=0.01,
            heartbeat_rx_callback=lambda payload: (rx_payloads.append(payload), event.set()),
        )
        client.disconnected = False
        await client.rx_queue.put(bytes.fromhex("7F 3E 21"))

        async def fake_write(payload, target):
            return None

        client._write_diagnostic = fake_write
        task = asyncio.create_task(client._heartbeat_loop())
        try:
            await asyncio.wait_for(event.wait(), timeout=1.0)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self.assertEqual(rx_payloads, [bytes.fromhex("7F 3E 21")])
        self.assertTrue(client.rx_queue.empty())


if __name__ == "__main__":
    unittest.main()
