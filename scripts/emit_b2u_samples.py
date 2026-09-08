"""Emit sample unpacked B2U trees under dist/b2u (no game videos)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config_scanner.b2u_pack import (  # noqa: E402
    pack_companion_update,
    pack_country_update,
    pack_egm_update,
    pack_tool_update,
    resolve_config_scanner_exe,
)
from config_scanner.companion_pack import CompanionKind, stage_companion_from_source  # noqa: E402
from config_scanner.cs_catalog import stage_country_pack  # noqa: E402
from config_scanner.slot_setup import (  # noqa: E402
    BillToken,
    MathDenomSettings,
    SasSettings,
    SlotSetupRecipe,
    build_config_pack,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _mini_goldclub(base: Path) -> Path:
    root = base / "Goldclub"
    _write(
        root / "slot" / "hwdrivers" / "Keyboard.xml",
        """<?xml version="1.0"?>
<config><mapping><ButtonMapping name="270">Spin</ButtonMapping></mapping></config>
""",
    )
    _write(
        root / "slot" / "hwdrivers" / "QuixantHardware.xml",
        """<?xml version="1.0"?>
<root><BillAcceptor>
  <comPortName>COM6</comPortName>
  <currentProtocol>MEI</currentProtocol>
  <currentProtocolSettings><Protocol>MEI</Protocol>
    <SupportedDevices><BillAcceptorProtocolDevice><Id>MEI</Id></BillAcceptorProtocolDevice></SupportedDevices>
    <TicketValue>111</TicketValue>
  </currentProtocolSettings>
</BillAcceptor></root>
""",
    )
    for proto in ("MEI", "JCM"):
        _write(
            root / "slot" / "hwdrivers" / "protocols" / "billacceptor" / f"BillAcceptor_{proto}.xml",
            f"<BillAcceptorProtocolSettings><Protocol>{proto}</Protocol></BillAcceptorProtocolSettings>\n",
        )
    _write(
        root / "slot" / "themes" / "HardwareConfig.xml",
        """<?xml version="1.0"?>
<HardwareSettings>
  <CurrencyName>USD</CurrencyName>
  <BillSettings><Bills>
    <TokenMapping Code="97" CanAccept="true" CanReturn="true" AcceptingDelayBetweenTokenInMS="0">100</TokenMapping>
  </Bills></BillSettings>
  <TicketPrinterSettings><OfflineEnabled>false</OfflineEnabled></TicketPrinterSettings>
</HardwareSettings>
""",
    )
    _write(
        root / "slot" / "themes" / "mgconfig.xml",
        """<?xml version="1.0"?>
<Multigamer>
  <MachineID>GST!!MachineName!!</MachineID>
  <DenominationList><int>5</int></DenominationList>
  <CreditRateValues><int>5</int></CreditRateValues>
</Multigamer>
""",
    )
    _write(
        root / "slot" / "themes" / "SampleGame" / "MathSettings.xml",
        """<?xml version="1.0"?>
<MathSettings><DenomConfig><DenomConfigSettings>
  <DenominationMultiplier>1</DenominationMultiplier>
  <FixedBet>1</FixedBet>
  <BetMultipliers><int>1</int><int>2</int></BetMultipliers>
  <ReturnPercent>return_94_0</ReturnPercent>
</DenomConfigSettings></DenomConfig></MathSettings>
""",
    )
    _write(
        root / "Services" / "aurum" / "config" / "SASControler1" / "ClientsSet.xml",
        """<?xml version="1.0"?>
<ClientsSet><Clients><SASClientState>
  <SASAddress>1</SASAddress>
  <AFT.anyAftEnabled>true</AFT.anyAftEnabled>
</SASClientState></Clients></ClientsSet>
""",
    )
    _write(
        root / "Services" / "aurum" / "config" / "SASControler1" / "SASsetupData.xml",
        """<?xml version="1.0"?>
<SASsetupData>
  <FundsTransferType>AFT</FundsTransferType>
  <LockGameWhenNoComms>true</LockGameWhenNoComms>
</SASsetupData>
""",
    )
    (root / "slot" / "OneHand.exe").write_bytes(b"MZ")
    return root


def _mini_country_tool(base: Path) -> Path:
    tool = base / "CountrySelectorTool"
    leaf = (
        tool
        / "data"
        / "SampleCountry"
        / "Gamestar 2 Screens"
        / "Gamestar SAS"
    )
    leaf.mkdir(parents=True)
    _write(
        leaf / "install.json",
        """{
  "Readme": "Sample country SAS-only leaf",
  "Delete": [],
  "Copy": [{"From": "slot", "To": "c:/Goldclub/Slot/"}],
  "Data": [{
    "Path": ["c:/Goldclub/Slot/themes/mgconfig.xml"],
    "Variables": [{"Title": "Machine number", "Pattern": "!!MachineName!!"}]
  }]
}
""",
    )
    _write(
        leaf / "slot" / "themes" / "mgconfig.xml",
        "<Multigamer><MachineID>GST!!MachineName!!</MachineID></Multigamer>\n",
    )
    return tool


def _mini_companion_bills(base: Path) -> Path:
    src = base / "BillsTTD-Sample"
    tmp = src / "Content" / "tmp"
    _write(
        tmp / "slot" / "themes" / "HardwareConfig.xml",
        "<HardwareSettings><CurrencyName>TTD</CurrencyName></HardwareSettings>\n",
    )
    (tmp / "OneHandConfigurer.exe").write_bytes(b"MZ")
    return src


def main() -> int:
    dist_b2u = _ROOT / "dist" / "b2u"
    dist_b2u.mkdir(parents=True, exist_ok=True)
    work = dist_b2u / "_sample_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    exe = resolve_config_scanner_exe()
    print(f"Using exe: {exe}")

    tool = pack_tool_update(
        dist_b2u, exe_path=exe, package_name="ConfigScanner_Tool", encrypt=True
    )
    print(tool.note)

    gold = _mini_goldclub(work)
    recipe = SlotSetupRecipe(
        label="Sample_EGM",
        sas=SasSettings(address=1, aft_enabled=True),
        bill_protocol="MEI",
        keyboard={"270": "Spin"},
        bill_tokens=[BillToken(code="97", value=100)],
        math=[
            MathDenomSettings(
                theme="SampleGame",
                denomination_multiplier=1,
                fixed_bet=1.0,
                bet_multipliers=[1, 2],
                return_percent="return_94_0",
            )
        ],
        denomination_list=[5],
        credit_rate_values=[5],
    )
    egm_pack = work / "egm-config-pack"
    build_config_pack(recipe, gold, egm_pack)
    egm = pack_egm_update(
        dist_b2u,
        egm_pack,
        exe_path=exe,
        package_name="ConfigScanner_EGM_Sample",
        encrypt=True,
    )
    print(egm.note)

    country_tool = _mini_country_tool(work)
    staged_cs = stage_country_pack(country_tool, work / "cs_stage")
    country = pack_country_update(
        dist_b2u,
        staged_cs,
        exe_path=exe,
        package_name="ConfigScanner_Country_Sample",
        encrypt=True,
    )
    print(country.note)

    bills_src = _mini_companion_bills(work)
    companion_stage = work / "companion_stage"
    stage_companion_from_source(
        bills_src, companion_stage, kind=CompanionKind.BILLS, label="BillsTTD_Sample"
    )
    companion = pack_companion_update(
        dist_b2u,
        companion_stage,
        exe_path=exe,
        package_name="ConfigScanner_Companion_Bills_Sample",
        encrypt=True,
    )
    print(companion.note)

    readme = dist_b2u / "README.txt"
    readme.write_text(
        "ConfigScanner B2U samples\n"
        "=========================\n"
        "ConfigScanner_Tool          — full GUI\n"
        "ConfigScanner_EGM_Sample    — --apply-pack recipe apply\n"
        "ConfigScanner_Country_Sample — --country-pack wizard\n"
        "ConfigScanner_Companion_Bills_Sample — --companion-pack bills\n"
        "\n"
        "*.b2u files appear when BiOS2_PackageGenerator.exe is available.\n"
        "Unpacked folders always work like _B2U share packages.\n",
        encoding="utf-8",
    )
    print(f"Wrote {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
