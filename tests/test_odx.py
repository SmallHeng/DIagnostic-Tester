from __future__ import annotations

import unittest
from pathlib import Path
from zipfile import ZipFile

from odx import (
    OdxDocument,
    build_index,
    decode_negative_response,
    describe_nrc,
    load_odx,
    load_pdx,
    resolve_inheritance,
    validate_database,
)


class OdxLoadTests(unittest.TestCase):
    def test_loads_odx_subset(self) -> None:
        tmp = Path(__file__).resolve().parent / ".tmp"
        tmp.mkdir(exist_ok=True)
        path = tmp / "odx_data.xml"
        path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<ODX>
  <DATA-OBJECT-PROP ID="DOP.VIN_ASCII" SHORT-NAME="DOP.VIN_ASCII">
    <DIAG-CODED-TYPE BASE-DATA-TYPE="A_ASCIISTRING" BIT-LENGTH="136" />
  </DATA-OBJECT-PROP>
  <REQUEST ID="REQ.READ_VIN" SHORT-NAME="REQ.READ_VIN">
    <BYTES>22 F1 90</BYTES>
  </REQUEST>
  <DIAG-SERVICE ID="SERVICE.READ_VIN" SHORT-NAME="Read VIN" SEMANTIC="READ-DATA-BY-IDENTIFIER">
    <REQUEST-REF ID-REF="REQ.READ_VIN" />
    <POS-RESPONSE>62 F1 90</POS-RESPONSE>
  </DIAG-SERVICE>
  <DIAG-LAYER SHORT-NAME="Gateway" LOGICAL-ADDRESS="0x1001" ROLE="gateway" ACCESS="direct">
    <DATA-IDENTIFIER ID="0xF190" SHORT-NAME="VIN" DESC="Vehicle identification number">
      <DOP-REF ID-REF="DOP.VIN_ASCII" />
    </DATA-IDENTIFIER>
    <ROUTINE ID="0xFF00" SHORT-NAME="Pre-programming routine" CONTROL="0x01" />
  </DIAG-LAYER>
  <DTC-DOP>
    <DTCS>
      <DTC TROUBLE-CODE="0x123456" DISPLAY-TROUBLE-CODE="P1234" TEXT="Demo DTC" SEVERITY="warning" />
    </DTCS>
  </DTC-DOP>
  <QUICK-ACTIONS>
    <ACTION SHORT-NAME="Read VIN" REQUEST="22 F1 90" />
  </QUICK-ACTIONS>
</ODX>
""",
            encoding="utf-8",
        )

        database = load_odx(path)

        self.assertEqual(database.ecus[0].name, "Gateway")
        self.assertEqual(database.ecus[0].address, "1001")
        self.assertEqual(database.ecus[0].role, "gateway")
        self.assertEqual(database.dids[0].did, "F190")
        self.assertEqual(database.dids[0].name, "VIN")
        self.assertEqual(database.routines[0].routine_id, "FF00")
        self.assertEqual(database.routines[0].control, "01")
        self.assertEqual(database.dtcs[0].code, "123456")
        self.assertEqual(database.dtcs[0].display_code, "P1234")
        self.assertEqual(database.dtcs[0].description, "Demo DTC")
        self.assertEqual(database.dtcs[0].severity, "warning")
        self.assertEqual(database.quick_actions[0].request, "22 F1 90")
        self.assertEqual(validate_database(database), [])
        index = build_index(database)
        self.assertEqual(index.dids["F190"].name, "VIN")
        self.assertEqual(index.routines["FF00"].name, "Pre-programming routine")
        self.assertEqual(index.dtcs["123456"].display_code, "P1234")
        self.assertEqual(index.service_for_request(bytes.fromhex("22 F1 90")).name, "Read VIN")
        self.assertEqual(index.dop_for_did("F190").name, "DOP.VIN_ASCII")
        self.assertEqual(database.request_for_did("F190"), bytes.fromhex("22 F1 90"))
        self.assertEqual(database.encode_did_value("F190", "LVDTESTSIM000001"), b"LVDTESTSIM000001\x00")
        self.assertEqual(
            database.decode_did_response("F190", bytes.fromhex("62 F1 90 4C 56 44 54 45 53 54 53 49 4D 30 30 30 30 30 31")),
            "LVDTESTSIM000001",
        )

    def test_loads_pdx_zip(self) -> None:
        tmp = Path(__file__).resolve().parent / ".tmp"
        tmp.mkdir(exist_ok=True)
        odx_text = """<?xml version="1.0" encoding="UTF-8"?>
<ODX>
  <DIAG-LAYER SHORT-NAME="Gateway" LOGICAL-ADDRESS="0x1001" ROLE="gateway" ACCESS="direct" />
</ODX>
"""
        path = tmp / "sample.pdx"
        with ZipFile(path, "w") as archive:
            archive.writestr("database.odx", odx_text)

        database = load_pdx(path)

        self.assertEqual(database.ecus[0].name, "Gateway")
        self.assertEqual(load_odx(path).ecus[0].address, "1001")

    def test_loads_nested_odx_style_subset(self) -> None:
        tmp = Path(__file__).resolve().parent / ".tmp"
        tmp.mkdir(exist_ok=True)
        path = tmp / "nested_style.odx"
        path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<ODX xmlns="http://example.invalid/odx">
  <DIAG-DATA-DICTIONARY-SPEC>
    <DATA-OBJECT-PROPS>
      <DATA-OBJECT-PROP ID="DOP.SPEED">
        <SHORT-NAME>DOP.SPEED</SHORT-NAME>
        <DIAG-CODED-TYPE>
          <STANDARD-LENGTH-TYPE BASE-DATA-TYPE="A_UINT16" BIT-LENGTH="16" />
        </DIAG-CODED-TYPE>
        <COMPU-METHOD-REF ID-REF="CM.SPEED" />
      </DATA-OBJECT-PROP>
    </DATA-OBJECT-PROPS>
    <COMPU-METHODS>
      <COMPU-METHOD ID="CM.SPEED">
        <SHORT-NAME>CM.SPEED</SHORT-NAME>
        <CATEGORY>LINEAR</CATEGORY>
        <UNIT>km/h</UNIT>
        <V>0</V>
        <V>0.01</V>
        <V>1</V>
      </COMPU-METHOD>
    </COMPU-METHODS>
  </DIAG-DATA-DICTIONARY-SPEC>
  <REQUESTS>
    <REQUEST ID="REQ.READ_SPEED">
      <SHORT-NAME>REQ.READ_SPEED</SHORT-NAME>
      <PARAMS>
        <PARAM SEMANTIC="SERVICE-ID">
          <CODED-VALUE>0x22</CODED-VALUE>
        </PARAM>
        <PARAM SEMANTIC="ID" BYTE-POSITION="1">
          <CODED-VALUE>0xF191</CODED-VALUE>
        </PARAM>
        <PARAM SEMANTIC="DATA" BYTE-POSITION="3" BYTE-LENGTH="2" TYPE="VALUE">
          <DOP-REF ID-REF="DOP.SPEED" />
        </PARAM>
      </PARAMS>
    </REQUEST>
  </REQUESTS>
  <POS-RESPONSES>
    <POS-RESPONSE ID="PR.READ_SPEED">
      <SHORT-NAME>PR.READ_SPEED</SHORT-NAME>
      <PARAMS>
        <PARAM BYTE-POSITION="0"><CODED-VALUE>0x62</CODED-VALUE></PARAM>
        <PARAM BYTE-POSITION="1"><CODED-VALUE>0xF191</CODED-VALUE></PARAM>
      </PARAMS>
    </POS-RESPONSE>
  </POS-RESPONSES>
  <NEG-RESPONSES>
    <NEG-RESPONSE ID="NR.READ_SPEED">
      <SHORT-NAME>NR.READ_SPEED</SHORT-NAME>
      <BYTES>7F 22</BYTES>
      <NRC-CONST CODED-VALUE="0x31" />
      <NRC-CONST CODED-VALUE="0x78" />
    </NEG-RESPONSE>
  </NEG-RESPONSES>
  <ECU-VARIANT ID="EV.GATEWAY">
    <SHORT-NAME>GatewayVariant</SHORT-NAME>
    <LOGICAL-ADDRESS>0x1001</LOGICAL-ADDRESS>
    <DATA-IDENTS>
      <DATA-IDENT ID="DI.SPEED">
        <SHORT-NAME>Vehicle speed</SHORT-NAME>
        <DATA-ID>0xF191</DATA-ID>
        <DOP-REF ID-REF="DOP.SPEED" />
      </DATA-IDENT>
    </DATA-IDENTS>
    <DIAG-COMMS>
      <DIAG-SERVICE ID="SERVICE.READ_SPEED">
        <SHORT-NAME>Read speed</SHORT-NAME>
        <SEMANTIC>READ-DATA-BY-IDENTIFIER</SEMANTIC>
        <REQUEST-SNREF SHORT-NAME="REQ.READ_SPEED" />
        <POS-RESPONSE-REF ID-REF="PR.READ_SPEED" />
        <NEG-RESPONSE-REF ID-REF="NR.READ_SPEED" />
      </DIAG-SERVICE>
    </DIAG-COMMS>
  </ECU-VARIANT>
</ODX>
""",
            encoding="utf-8",
        )

        database = load_odx(path)

        self.assertEqual(database.ecus[0].name, "GatewayVariant")
        self.assertEqual(database.ecus[0].address, "1001")
        self.assertEqual(database.ecus[0].role, "ecu")
        self.assertEqual(database.dids[0].did, "F191")
        self.assertEqual(database.dids[0].name, "Vehicle speed")
        self.assertEqual(database.dops["DOP.SPEED"].base_data_type, "A_UINT16")
        self.assertEqual(database.dops["DOP.SPEED"].byte_length, 2)
        self.assertEqual(database.request_for_did("F191"), bytes.fromhex("22 F1 91"))
        self.assertEqual(database.services[0].positive_response.payload_prefix, bytes.fromhex("62 F1 91"))
        self.assertEqual(database.services[0].negative_responses[0].nrcs, [0x31, 0x78])
        self.assertEqual(describe_nrc(0x31), "Request Out Of Range")
        self.assertEqual(decode_negative_response(bytes.fromhex("7F 22 78")), (0x22, 0x78, "Response Pending"))
        self.assertEqual(len(database.services[0].request_parameters), 3)
        self.assertEqual(database.services[0].request_parameters[0].semantic, "SERVICE-ID")
        self.assertEqual(database.services[0].request_parameters[0].coded_value, 0x22)
        self.assertEqual(database.services[0].request_parameters[1].byte_position, 1)
        self.assertEqual(database.services[0].request_parameters[1].coded_value, 0xF191)
        self.assertEqual(database.services[0].request_parameters[2].dop_ref, "DOP.SPEED")
        self.assertTrue(database.services[0].request_parameters[2].is_input)
        self.assertEqual(database.services[0].request_parameters[2].byte_length, 2)
        self.assertEqual(len(database.services[0].positive_response.parameters), 2)
        self.assertEqual(database.services[0].positive_response.parameters[0].coded_value, 0x62)
        self.assertEqual(database.decode_did_response("F191", bytes.fromhex("62 F1 91 27 10")), "100 km/h")
        self.assertEqual(database.encode_did_value("F191", 100), bytes.fromhex("27 10"))
        index = build_index(database)
        self.assertEqual(index.dop_for_did("F191").name, "DOP.SPEED")
        self.assertEqual(index.computation_for_dop(index.dop_for_did("F191")).name, "CM.SPEED")
        self.assertEqual(index.services_with_input_parameters()[0].name, "Read speed")
        self.assertEqual(resolve_inheritance(database).services[0].name, "Read speed")

    def test_texttable_compu_and_document_model(self) -> None:
        text = """<?xml version="1.0" encoding="UTF-8"?>
<ODX>
  <DATA-OBJECT-PROP ID="DOP.SWITCH" SHORT-NAME="DOP.SWITCH">
    <DIAG-CODED-TYPE BASE-DATA-TYPE="A_UINT8" BIT-LENGTH="8" />
    <COMPU-METHOD-REF ID-REF="CM.SWITCH" />
  </DATA-OBJECT-PROP>
  <COMPU-METHOD ID="CM.SWITCH">
    <SHORT-NAME>CM.SWITCH</SHORT-NAME>
    <CATEGORY>TEXTTABLE</CATEGORY>
    <COMPU-SCALE>
      <LOWER-LIMIT>0</LOWER-LIMIT>
      <VT>OFF</VT>
    </COMPU-SCALE>
    <COMPU-SCALE>
      <LOWER-LIMIT>1</LOWER-LIMIT>
      <VT>ON</VT>
    </COMPU-SCALE>
  </COMPU-METHOD>
  <DIAG-LAYER SHORT-NAME="Body" LOGICAL-ADDRESS="0x1002">
    <DATA-IDENTIFIER ID="0xF1A0" SHORT-NAME="Switch">
      <DOP-REF ID-REF="DOP.SWITCH" />
    </DATA-IDENTIFIER>
  </DIAG-LAYER>
</ODX>
"""
        tmp = Path(__file__).resolve().parent / ".tmp"
        path = tmp / "texttable.odx"
        path.write_text(text, encoding="utf-8")

        database = load_odx(path)
        document = OdxDocument.from_text(text)

        self.assertEqual(database.decode_did_response("F1A0", bytes.fromhex("62 F1 A0 01")), "ON")
        self.assertEqual(database.encode_did_value("F1A0", "OFF"), bytes.fromhex("00"))
        self.assertTrue(any(node.node_type == "did" for node in document.nodes))
        self.assertEqual(document.nodes[0].path, ())

    def test_validation_reports_missing_references_and_empty_services(self) -> None:
        tmp = Path(__file__).resolve().parent / ".tmp"
        tmp.mkdir(exist_ok=True)
        path = tmp / "invalid_refs.odx"
        path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<ODX>
  <DATA-OBJECT-PROP ID="DOP.MISSING_COMPU" SHORT-NAME="DOP.MISSING_COMPU">
    <DIAG-CODED-TYPE BASE-DATA-TYPE="A_UINT8" BIT-LENGTH="8" />
    <COMPU-METHOD-REF ID-REF="CM.DOES_NOT_EXIST" />
  </DATA-OBJECT-PROP>
  <DIAG-LAYER SHORT-NAME="Gateway" LOGICAL-ADDRESS="0x1001">
    <DATA-IDENTIFIER ID="0xF199" SHORT-NAME="Broken DID">
      <DOP-REF ID-REF="DOP.DOES_NOT_EXIST" />
    </DATA-IDENTIFIER>
  </DIAG-LAYER>
  <DIAG-SERVICE SHORT-NAME="Empty service" />
  <DIAG-SERVICE SHORT-NAME="Broken parameter service">
    <REQUEST>
      <PARAM SEMANTIC="DATA" TYPE="VALUE">
        <DOP-REF ID-REF="DOP.PARAM_MISSING" />
      </PARAM>
    </REQUEST>
  </DIAG-SERVICE>
</ODX>
""",
            encoding="utf-8",
        )

        issues = validate_database(load_odx(path))
        codes = {issue.code for issue in issues}

        self.assertIn("missing-dop-ref", codes)
        self.assertIn("missing-compu-method-ref", codes)
        self.assertIn("empty-service-request", codes)
        self.assertIn("missing-parameter-dop-ref", codes)

    def test_units_structures_and_service_request_encoding(self) -> None:
        tmp = Path(__file__).resolve().parent / ".tmp"
        tmp.mkdir(exist_ok=True)
        path = tmp / "structures.odx"
        path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<ODX>
  <UNIT ID="UNIT.VOLT">
    <SHORT-NAME>UNIT.VOLT</SHORT-NAME>
    <DISPLAY-NAME>V</DISPLAY-NAME>
  </UNIT>
  <DATA-OBJECT-PROP ID="DOP.VOLTAGE" SHORT-NAME="DOP.VOLTAGE">
    <DIAG-CODED-TYPE BASE-DATA-TYPE="A_UINT16" BIT-LENGTH="16" />
    <COMPU-METHOD-REF ID-REF="CM.VOLTAGE" />
  </DATA-OBJECT-PROP>
  <DATA-OBJECT-PROP ID="DOP.STATE" SHORT-NAME="DOP.STATE">
    <DIAG-CODED-TYPE BASE-DATA-TYPE="A_UINT8" BIT-LENGTH="8" />
    <COMPU-METHOD-REF ID-REF="CM.STATE" />
  </DATA-OBJECT-PROP>
  <COMPU-METHOD ID="CM.VOLTAGE">
    <SHORT-NAME>CM.VOLTAGE</SHORT-NAME>
    <CATEGORY>SCALE-LINEAR</CATEGORY>
    <UNIT-REF ID-REF="UNIT.VOLT" />
    <V>0</V>
    <V>0.1</V>
    <V>1</V>
  </COMPU-METHOD>
  <COMPU-METHOD ID="CM.STATE">
    <SHORT-NAME>CM.STATE</SHORT-NAME>
    <CATEGORY>TEXTTABLE</CATEGORY>
    <COMPU-SCALE><LOWER-LIMIT>0</LOWER-LIMIT><VT>OFF</VT></COMPU-SCALE>
    <COMPU-SCALE><LOWER-LIMIT>1</LOWER-LIMIT><VT>ON</VT></COMPU-SCALE>
  </COMPU-METHOD>
  <STRUCTURE ID="STRUCT.BATTERY" SHORT-NAME="STRUCT.BATTERY">
    <PARAM SHORT-NAME="Voltage" BYTE-POSITION="0">
      <DOP-REF ID-REF="DOP.VOLTAGE" />
    </PARAM>
    <PARAM SHORT-NAME="State" BYTE-POSITION="2">
      <DOP-REF ID-REF="DOP.STATE" />
    </PARAM>
  </STRUCTURE>
  <REQUEST ID="REQ.WRITE_BATTERY" SHORT-NAME="REQ.WRITE_BATTERY">
    <PARAM SHORT-NAME="SID" BYTE-POSITION="0"><CODED-VALUE>0x2E</CODED-VALUE></PARAM>
    <PARAM SHORT-NAME="DID" BYTE-POSITION="1"><CODED-VALUE>0xF1B0</CODED-VALUE></PARAM>
    <PARAM SHORT-NAME="BatteryData" BYTE-POSITION="3">
      <STRUCTURE-REF ID-REF="STRUCT.BATTERY" />
    </PARAM>
  </REQUEST>
  <DIAG-SERVICE ID="SERVICE.WRITE_BATTERY" SHORT-NAME="Write battery" SEMANTIC="WRITE-DATA-BY-IDENTIFIER">
    <REQUEST-REF ID-REF="REQ.WRITE_BATTERY" />
    <POS-RESPONSE>6E F1 B0</POS-RESPONSE>
  </DIAG-SERVICE>
  <DIAG-LAYER SHORT-NAME="Battery" LOGICAL-ADDRESS="0x1003">
    <DATA-IDENTIFIER ID="0xF1B0" SHORT-NAME="Battery data">
      <DOP-REF ID-REF="STRUCT.BATTERY" />
    </DATA-IDENTIFIER>
  </DIAG-LAYER>
</ODX>
""",
            encoding="utf-8",
        )

        database = load_odx(path)

        self.assertEqual(database.units["UNIT.VOLT"].label, "V")
        self.assertEqual(database.computations["CM.VOLTAGE"].unit, "V")
        self.assertEqual(database.structures["STRUCT.BATTERY"].fields[0].name, "Voltage")
        self.assertEqual(database.decode_did_response("F1B0", bytes.fromhex("62 F1 B0 00 7B 01")), "Voltage=12.3 V; State=ON")
        self.assertEqual(
            database.encode_did_value("F1B0", {"Voltage": 12.3, "State": "OFF"}),
            bytes.fromhex("00 7B 00"),
        )
        self.assertEqual(
            database.encode_service_request("Write battery", {"BatteryData": {"Voltage": 12.3, "State": "ON"}}),
            bytes.fromhex("2E F1 B0 00 7B 01"),
        )
        self.assertEqual(validate_database(database), [])

    def test_tmp_odx_pdx_samples_load_as_smoke_test(self) -> None:
        tmp = Path(__file__).resolve().parent / ".tmp"
        samples = sorted(path for path in tmp.glob("*") if path.suffix.lower() in {".odx", ".xml", ".pdx"})
        self.assertTrue(samples, "Expected at least one ODX/PDX sample in tests/.tmp")
        for sample in samples:
            with self.subTest(sample=sample.name):
                database = load_odx(sample)
                issues = validate_database(database)
                self.assertIsInstance(database.ecus, list)
                self.assertIsInstance(database.services, list)
                self.assertIsInstance(issues, list)


if __name__ == "__main__":
    unittest.main()
