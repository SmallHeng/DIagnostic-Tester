import asyncio
import unittest
from pathlib import Path

from diagnostic_simulator.config import ConfigStore
from diagnostic_simulator.uds import UDSDispatcher


XML = """<?xml version="1.0"?>
<Simulator vin="TESTVIN000000000" logical_address="0x0E00">
  <Ecus>
    <Ecu name="Gateway" address="0x1001" role="gateway" access="direct" s3_timeout="0.2">
      <Dtcs>
        <Dtc code="0x123456" status="0x09" severity="0x20" functional_unit="0x10" fault_detection_counter="0x7F" snapshot="01 02 AA BB" extended_data="01 CC DD" permanent="true" />
        <Dtc code="0x223344" status="0x2F" severity="0x40" functional_unit="0x20" fault_detection_counter="0x22" memory="mirror" />
        <Dtc code="0x334455" status="0x04" severity="0x10" functional_unit="0x30" fault_detection_counter="0x05" memory="obd" />
      </Dtcs>
      <Security>
        <Level name="level1" request_seed="0x01" send_key="0x02" seed="12 34 56 78" key="87 65 43 21" max_attempts="2" lock_time="0.2" />
      </Security>
      <Download start_address="0x00010000" end_address="0x0001FFFF" max_block_length="0x04" required_session="0x03" required_security="level1" />
      <Service id="0x11" handler="ecu_reset" />
      <Service id="0x14" handler="clear_dtc" />
      <Service id="0x19" handler="dtc" />
      <Service id="0x27" handler="security_access" />
      <Service id="0x22">
        <Data did="0xF187" response_mode="sequential">
          <Response>62 F1 87 01</Response>
          <Response>62 F1 87 02</Response>
        </Data>
        <Data did="0xF18C" simulate_pending="true" total_delay="0.12" pending_interval="0.05">
          <Response>62 F1 8C 99</Response>
        </Data>
      </Service>
      <Service id="0x36" handler="dynamic_echo" />
      <Service id="0x29" handler="mock_auth" />
      <Service id="0x2E" required_session="0x03" required_security="level1">
        <Data request="2E F1 91 12 34">
          <Response>6E F1 91</Response>
        </Data>
      </Service>
      <Service id="0x34" handler="download" />
      <Service id="0x37" handler="transfer_exit" />
    </Ecu>
    <Ecu name="ProxiedBody" address="0x1002" role="ecu" access="proxied" gateway="0x1001">
      <Service id="0x22">
        <Data did="0xF190">
          <Response>62 F1 90 50 52 4F 58 59</Response>
        </Data>
      </Service>
    </Ecu>
    <Ecu name="InvalidProxied" address="0x1003" role="ecu" access="proxied" gateway="0x1999">
      <Service id="0x22">
        <Data did="0xF190">
          <Response>62 F1 90 42 41 44</Response>
        </Data>
      </Service>
    </Ecu>
    <Ecu name="MissingGateway" address="0x1004" role="ecu" access="proxied">
      <Service id="0x22">
        <Data did="0xF190">
          <Response>62 F1 90 4D 49 53 53</Response>
        </Data>
      </Service>
    </Ecu>
  </Ecus>
</Simulator>
"""


class UDSTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(__file__).resolve().parent / ".tmp"
        self.tmp.mkdir(exist_ok=True)
        self.config_path = self.tmp / f"{self._testMethodName}.xml"
        self.config_path.write_text(XML, encoding="utf-8")
        self.dispatcher = UDSDispatcher(ConfigStore(self.config_path))

    async def asyncTearDown(self):
        if self.config_path.exists():
            self.config_path.unlink()

    async def test_sequential_response_cycles(self):
        first = await self.dispatcher.dispatch(0x1001, bytes.fromhex("22 F1 87"))
        second = await self.dispatcher.dispatch(0x1001, bytes.fromhex("22 F1 87"))
        third = await self.dispatcher.dispatch(0x1001, bytes.fromhex("22 F1 87"))

        self.assertEqual(first, bytes.fromhex("62 F1 87 01"))
        self.assertEqual(second, bytes.fromhex("62 F1 87 02"))
        self.assertEqual(third, bytes.fromhex("62 F1 87 01"))

    async def test_dynamic_echo_uses_block_sequence_counter(self):
        await self._unlock_programming()
        response = await self.dispatcher.dispatch(0x1001, bytes.fromhex("36 7A AA BB"))

        self.assertEqual(response, bytes.fromhex("76 7A"))

    async def test_pending_callback_precedes_final_response(self):
        pending = []

        async def send_pending(payload):
            pending.append(payload)

        response = await self.dispatcher.dispatch(0x1001, bytes.fromhex("22 F1 8C"), send_pending)

        self.assertEqual(response, bytes.fromhex("62 F1 8C 99"))
        self.assertGreaterEqual(len(pending), 1)
        self.assertTrue(all(item == bytes.fromhex("7F 22 78") for item in pending))

    async def test_mock_auth_unlocks_state(self):
        challenge = await self.dispatcher.dispatch(0x1001, bytes.fromhex("29 01"))
        unlocked = await self.dispatcher.dispatch(0x1001, bytes.fromhex("29 03"))

        self.assertEqual(challenge[:2], bytes.fromhex("69 01"))
        self.assertEqual(len(challenge), 18)
        self.assertEqual(unlocked, bytes.fromhex("69 03"))
        self.assertTrue(self.dispatcher.states[0x1001].authenticated)

    async def test_s3_watchdog_returns_to_default_session(self):
        response = await self.dispatcher.dispatch(0x1001, bytes.fromhex("10 03"))
        self.assertEqual(response[:2], bytes.fromhex("50 03"))

        await asyncio.sleep(0.25)

        self.assertEqual(self.dispatcher.states[0x1001].session, 0x01)

    async def test_read_dtc_information_common_subfunctions(self):
        count = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 01 FF"))
        by_status = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 02 09"))
        snapshot = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 04 12 34 56 01"))
        extended = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 06 12 34 56 01"))
        supported = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 0A"))
        mirror_count = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 11 FF"))
        obd_count = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 12 FF"))
        fdc = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 14"))
        permanent = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 15"))
        severity_count = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 07 20 FF"))
        severity_info = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 08 12 34 56"))
        by_severity = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 09 20 FF"))

        self.assertEqual(count, bytes.fromhex("59 01 FF 01 00 03"))
        self.assertEqual(by_status, bytes.fromhex("59 02 FF 12 34 56 09 22 33 44 2F"))
        self.assertEqual(snapshot, bytes.fromhex("59 04 12 34 56 09 01 01 02 AA BB"))
        self.assertEqual(extended, bytes.fromhex("59 06 12 34 56 09 01 01 CC DD"))
        self.assertEqual(supported, bytes.fromhex("59 0A 12 34 56 09 22 33 44 2F 33 44 55 04"))
        self.assertEqual(mirror_count, bytes.fromhex("59 11 FF 01 00 01"))
        self.assertEqual(obd_count, bytes.fromhex("59 12 FF 01 00 01"))
        self.assertEqual(fdc, bytes.fromhex("59 14 12 34 56 7F 22 33 44 22 33 44 55 05"))
        self.assertEqual(permanent, bytes.fromhex("59 15 12 34 56 09"))
        self.assertEqual(severity_count, bytes.fromhex("59 07 FF 01 00 01"))
        self.assertEqual(severity_info, bytes.fromhex("59 08 20 10 12 34 56 09"))
        self.assertEqual(by_severity, bytes.fromhex("59 09 FF 20 10 12 34 56 09"))

    async def test_clear_diagnostic_information_updates_19_results(self):
        before = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 01 FF"))
        clear = await self.dispatcher.dispatch(0x1001, bytes.fromhex("14 FF FF FF"))
        after = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 01 FF"))

        self.assertEqual(before, bytes.fromhex("59 01 FF 01 00 03"))
        self.assertEqual(clear, bytes.fromhex("54"))
        self.assertEqual(after, bytes.fromhex("59 01 FF 01 00 00"))

    async def test_clear_diagnostic_information_respects_clearable_and_clear_status(self):
        xml = XML.replace(
            '<Dtc code="0x123456" status="0x09" severity="0x20" functional_unit="0x10" fault_detection_counter="0x7F" snapshot="01 02 AA BB" extended_data="01 CC DD" permanent="true" />',
            '<Dtc code="0x123456" status="0x09" severity="0x20" functional_unit="0x10" fault_detection_counter="0x7F" snapshot="01 02 AA BB" extended_data="01 CC DD" permanent="true" clear_status="0x08" clear_fault_detection_counter="0x01" />',
        ).replace(
            '<Dtc code="0x223344" status="0x2F" severity="0x40" functional_unit="0x20" fault_detection_counter="0x22" memory="mirror" />',
            '<Dtc code="0x223344" status="0x2F" severity="0x40" functional_unit="0x20" fault_detection_counter="0x22" memory="mirror" clearable="false" />',
        )
        self.config_path.write_text(xml, encoding="utf-8")
        dispatcher = UDSDispatcher(ConfigStore(self.config_path))

        clear = await dispatcher.dispatch(0x1001, bytes.fromhex("14 FF FF FF"))
        after = await dispatcher.dispatch(0x1001, bytes.fromhex("19 02 FF"))
        fdc = await dispatcher.dispatch(0x1001, bytes.fromhex("19 14"))

        self.assertEqual(clear, bytes.fromhex("54"))
        self.assertEqual(after, bytes.fromhex("59 02 FF 12 34 56 08 22 33 44 2F"))
        self.assertEqual(fdc, bytes.fromhex("59 14 12 34 56 01 22 33 44 22"))

    async def test_ecu_reset_restores_session_auth_counters_and_dtcs(self):
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("10 03"))
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("29 03"))
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("22 F1 87"))
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("14 FF FF FF"))

        reset = await self.dispatcher.dispatch(0x1001, bytes.fromhex("11 01"))
        dtc_count = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 01 FF"))
        first_sequence = await self.dispatcher.dispatch(0x1001, bytes.fromhex("22 F1 87"))

        state = self.dispatcher.states[0x1001]
        self.assertEqual(reset, bytes.fromhex("51 01"))
        self.assertEqual(state.session, 0x01)
        self.assertFalse(state.authenticated)
        self.assertEqual(dtc_count, bytes.fromhex("59 01 FF 01 00 03"))
        self.assertEqual(first_sequence, bytes.fromhex("62 F1 87 01"))

    async def test_ecu_reset_can_preserve_dtc_state_and_reject_unsupported_type(self):
        xml = XML.replace(
            '<Service id="0x11" handler="ecu_reset" />',
            '<Service id="0x11" handler="ecu_reset" supported_reset_types="0x01,0x03" restore_dtcs_on_reset="false" />',
        )
        self.config_path.write_text(xml, encoding="utf-8")
        dispatcher = UDSDispatcher(ConfigStore(self.config_path))

        await dispatcher.dispatch(0x1001, bytes.fromhex("14 FF FF FF"))
        unsupported = await dispatcher.dispatch(0x1001, bytes.fromhex("11 02"))
        reset = await dispatcher.dispatch(0x1001, bytes.fromhex("11 03"))
        dtc_count = await dispatcher.dispatch(0x1001, bytes.fromhex("19 01 FF"))

        self.assertEqual(unsupported, bytes.fromhex("7F 11 12"))
        self.assertEqual(reset, bytes.fromhex("51 03"))
        self.assertEqual(dtc_count, bytes.fromhex("59 01 FF 01 00 00"))

    async def test_common_negative_response_length_and_sequence_rules(self):
        bad_19_length = await self.dispatcher.dispatch(0x1001, bytes.fromhex("19 02 FF 00"))
        bad_11_length = await self.dispatcher.dispatch(0x1001, bytes.fromhex("11 01 00"))
        bad_tester_present_subfunction = await self.dispatcher.dispatch(0x1001, bytes.fromhex("3E 01"))

        self.assertEqual(bad_19_length, bytes.fromhex("7F 19 13"))
        self.assertEqual(bad_11_length, bytes.fromhex("7F 11 13"))
        self.assertEqual(bad_tester_present_subfunction, bytes.fromhex("7F 3E 12"))

    async def test_ecu_reset_disconnect_mode_marks_reboot_window_once(self):
        xml = XML.replace(
            '<Service id="0x11" handler="ecu_reset" />',
            '<Service id="0x11" handler="ecu_reset" reset_behavior="disconnect" reset_delay="0.15" />',
        )
        self.config_path.write_text(xml, encoding="utf-8")
        dispatcher = UDSDispatcher(ConfigStore(self.config_path))

        reset = await dispatcher.dispatch(0x1001, bytes.fromhex("11 01"))
        immediate = await dispatcher.dispatch(0x1001, bytes.fromhex("19 01 FF"))

        self.assertEqual(reset, bytes.fromhex("51 01"))
        self.assertTrue(dispatcher.should_disconnect_after_response(0x1001))
        self.assertFalse(dispatcher.should_disconnect_after_response(0x1001))
        self.assertEqual(immediate, bytes.fromhex("7F 19 21"))

        await asyncio.sleep(0.2)
        recovered = await dispatcher.dispatch(0x1001, bytes.fromhex("19 01 FF"))

        self.assertEqual(recovered, bytes.fromhex("59 01 FF 01 00 03"))

    async def test_direct_and_valid_proxied_ecus_are_routable(self):
        direct = await self.dispatcher.dispatch(0x1001, bytes.fromhex("22 F1 87"))
        proxied = await self.dispatcher.dispatch(0x1002, bytes.fromhex("22 F1 90"))

        self.assertEqual(direct, bytes.fromhex("62 F1 87 01"))
        self.assertEqual(proxied, bytes.fromhex("62 F1 90 50 52 4F 58 59"))

    async def test_proxied_ecu_requires_valid_gateway_role(self):
        invalid_gateway = await self.dispatcher.dispatch(0x1003, bytes.fromhex("22 F1 90"))
        missing_gateway = await self.dispatcher.dispatch(0x1004, bytes.fromhex("22 F1 90"))

        self.assertEqual(invalid_gateway, bytes.fromhex("7F 22 31"))
        self.assertEqual(missing_gateway, bytes.fromhex("7F 22 31"))

    async def test_security_access_seed_key_unlocks_level(self):
        seed = await self.dispatcher.dispatch(0x1001, bytes.fromhex("27 01"))
        key = await self.dispatcher.dispatch(0x1001, bytes.fromhex("27 02 87 65 43 21"))

        self.assertEqual(seed, bytes.fromhex("67 01 12 34 56 78"))
        self.assertEqual(key, bytes.fromhex("67 02"))
        self.assertIn("level1", self.dispatcher.states[0x1001].unlocked_security_levels)

    async def test_security_access_invalid_key_locks_after_max_attempts(self):
        first = await self.dispatcher.dispatch(0x1001, bytes.fromhex("27 02 00 00 00 00"))
        second = await self.dispatcher.dispatch(0x1001, bytes.fromhex("27 02 00 00 00 00"))
        locked = await self.dispatcher.dispatch(0x1001, bytes.fromhex("27 01"))

        self.assertEqual(first, bytes.fromhex("7F 27 35"))
        self.assertEqual(second, bytes.fromhex("7F 27 36"))
        self.assertEqual(locked, bytes.fromhex("7F 27 37"))

        await asyncio.sleep(0.25)
        seed = await self.dispatcher.dispatch(0x1001, bytes.fromhex("27 01"))
        self.assertEqual(seed, bytes.fromhex("67 01 12 34 56 78"))

    async def test_required_session_and_security_are_enforced(self):
        default_session = await self.dispatcher.dispatch(0x1001, bytes.fromhex("2E F1 91 12 34"))
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("10 03"))
        locked = await self.dispatcher.dispatch(0x1001, bytes.fromhex("2E F1 91 12 34"))
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("27 01"))
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("27 02 87 65 43 21"))
        unlocked = await self.dispatcher.dispatch(0x1001, bytes.fromhex("2E F1 91 12 34"))

        self.assertEqual(default_session, bytes.fromhex("7F 2E 7F"))
        self.assertEqual(locked, bytes.fromhex("7F 2E 33"))
        self.assertEqual(unlocked, bytes.fromhex("6E F1 91"))

    async def _unlock_programming(self):
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("10 03"))
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("27 01"))
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("27 02 87 65 43 21"))

    async def test_request_download_transfer_data_and_exit_success(self):
        await self._unlock_programming()

        download = await self.dispatcher.dispatch(0x1001, bytes.fromhex("34 00 44 00 01 00 00 00 00 00 04"))
        block1 = await self.dispatcher.dispatch(0x1001, bytes.fromhex("36 01 AA BB"))
        block2 = await self.dispatcher.dispatch(0x1001, bytes.fromhex("36 02 CC DD"))
        exit_response = await self.dispatcher.dispatch(0x1001, bytes.fromhex("37"))

        self.assertEqual(download, bytes.fromhex("74 20 00 04"))
        self.assertEqual(block1, bytes.fromhex("76 01"))
        self.assertEqual(block2, bytes.fromhex("76 02"))
        self.assertEqual(exit_response, bytes.fromhex("77"))

    async def test_request_download_requires_session_and_security(self):
        default_session = await self.dispatcher.dispatch(0x1001, bytes.fromhex("34 00 44 00 01 00 00 00 00 00 04"))
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("10 03"))
        locked = await self.dispatcher.dispatch(0x1001, bytes.fromhex("34 00 44 00 01 00 00 00 00 00 04"))

        self.assertEqual(default_session, bytes.fromhex("7F 34 7F"))
        self.assertEqual(locked, bytes.fromhex("7F 34 33"))

    async def test_transfer_data_repeated_and_wrong_block_sequence(self):
        await self._unlock_programming()
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("34 00 44 00 01 00 00 00 00 00 04"))

        block1 = await self.dispatcher.dispatch(0x1001, bytes.fromhex("36 01 AA BB"))
        duplicate = await self.dispatcher.dispatch(0x1001, bytes.fromhex("36 01 AA BB"))
        wrong = await self.dispatcher.dispatch(0x1001, bytes.fromhex("36 03 CC DD"))

        self.assertEqual(block1, bytes.fromhex("76 01"))
        self.assertEqual(duplicate, bytes.fromhex("76 01"))
        self.assertEqual(wrong, bytes.fromhex("7F 36 73"))

    async def test_transfer_exit_requires_complete_download(self):
        await self._unlock_programming()
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("34 00 44 00 01 00 00 00 00 00 04"))
        await self.dispatcher.dispatch(0x1001, bytes.fromhex("36 01 AA BB"))

        response = await self.dispatcher.dispatch(0x1001, bytes.fromhex("37"))

        self.assertEqual(response, bytes.fromhex("7F 37 71"))

    async def test_download_rejects_out_of_range_address(self):
        await self._unlock_programming()

        response = await self.dispatcher.dispatch(0x1001, bytes.fromhex("34 00 44 00 02 00 00 00 00 00 04"))

        self.assertEqual(response, bytes.fromhex("7F 34 31"))


if __name__ == "__main__":
    unittest.main()
