"""Tests for Slot EGM setup recipe / XML patch / apply."""

from __future__ import annotations

from pathlib import Path

from config_scanner.slot_setup import (
    BillToken,
    MathDenomSettings,
    SasSettings,
    SlotSetupRecipe,
    TICKET_HW_DRIVER,
    TTD_MEI_BILL_TOKENS,
    apply_config_pack,
    build_config_pack,
    default_bill_tokens_for_currency,
    goldclub_root_from_target,
    load_recipe,
    load_recipe_from_goldclub,
    mei_bill_token_issues,
    normalize_mei_bill_tokens_for_currency,
    patch_hardware_config,
    patch_keyboard_xml,
    patch_quixant_bill_protocol,
    patch_tito_ticket_driver,
    read_bill_protocol,
    read_bill_tokens,
    read_keyboard_map,
    read_ticket_protocol,
    recipe_summary_lines,
    save_recipe,
    ticket_protocol_from_hw_driver,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fake_goldclub(tmp_path: Path) -> Path:
    root = tmp_path / "Goldclub"
    _write(
        root / "slot" / "hwdrivers" / "Keyboard.xml",
        """<?xml version="1.0"?>
<config>
  <mapping>
    <ButtonMapping name="261">Collect</ButtonMapping>
    <ButtonMapping name="270">Spin</ButtonMapping>
  </mapping>
</config>
""",
    )
    _write(
        root / "slot" / "hwdrivers" / "QuixantHardware.xml",
        """<?xml version="1.0"?>
<root>
  <BillAcceptor>
    <enable>true</enable>
    <comPortName>COM6</comPortName>
    <currentProtocol>JCM</currentProtocol>
    <currentProtocolSettings>
      <Protocol>JCM</Protocol>
      <SupportedDevices>
        <BillAcceptorProtocolDevice>
          <Id>JCM UBA10</Id>
        </BillAcceptorProtocolDevice>
      </SupportedDevices>
      <TicketValue>111</TicketValue>
    </currentProtocolSettings>
  </BillAcceptor>
</root>
""",
    )
    _write(
        root
        / "slot"
        / "hwdrivers"
        / "protocols"
        / "billacceptor"
        / "BillAcceptor_MEI.xml",
        """<?xml version="1.0"?>
<BillAcceptorProtocolSettings>
  <Protocol>MEI</Protocol>
  <SupportedDevices>
    <BillAcceptorProtocolDevice><Id>MEI</Id></BillAcceptorProtocolDevice>
  </SupportedDevices>
  <TicketValue>111</TicketValue>
</BillAcceptorProtocolSettings>
""",
    )
    _write(
        root
        / "slot"
        / "hwdrivers"
        / "protocols"
        / "billacceptor"
        / "BillAcceptor_JCM.xml",
        """<?xml version="1.0"?>
<BillAcceptorProtocolSettings>
  <Protocol>JCM</Protocol>
  <SupportedDevices>
    <BillAcceptorProtocolDevice><Id>JCM UBA10</Id></BillAcceptorProtocolDevice>
  </SupportedDevices>
  <TicketValue>111</TicketValue>
</BillAcceptorProtocolSettings>
""",
    )
    _write(
        root / "slot" / "themes" / "HardwareConfig.xml",
        """<?xml version="1.0"?>
<HardwareSettings>
  <CurrencyName>USD</CurrencyName>
  <BillSettings>
    <Enabled>true</Enabled>
    <StackerInstalledAutoUnlock>true</StackerInstalledAutoUnlock>
    <Bills>
      <TokenMapping Code="97" CanAccept="true" CanReturn="true" AcceptingDelayBetweenTokenInMS="0">100</TokenMapping>
      <TokenMapping Code="99" CanAccept="true" CanReturn="true" AcceptingDelayBetweenTokenInMS="0">500</TokenMapping>
    </Bills>
  </BillSettings>
  <TicketPrinterSettings>
    <OfflineEnabled>false</OfflineEnabled>
    <RedeemEnabled>true</RedeemEnabled>
    <UseCurrencyISO>true</UseCurrencyISO>
    <LayoutJackpotReceiptTicket>jackpotreceipt0</LayoutJackpotReceiptTicket>
  </TicketPrinterSettings>
  <DallasKeySettings>
    <Permissions>
      <DallasKey>
        <Code>0100000000000282</Code>
        <Groups><string>Attendant</string></Groups>
        <Unlock>true</Unlock>
      </DallasKey>
      <DallasKey>
        <Code>IGTKeyAudit</Code>
        <Groups><string>Attendant</string></Groups>
        <Unlock>true</Unlock>
      </DallasKey>
    </Permissions>
  </DallasKeySettings>
</HardwareSettings>
""",
    )
    _write(
        root / "slot" / "themes" / "jurisdiction_config.xml",
        """<?xml version="1.0"?>
<JurisdictionSettings>
  <Tag>PuertoRico</Tag>
  <CultureInformation>
    <CultureName>es-PR</CultureName>
  </CultureInformation>
  <CurrencyDisplaySettings>
    <CurrencyName>USD</CurrencyName>
    <CurrencySymbol>$</CurrencySymbol>
  </CurrencyDisplaySettings>
  <MagicWheelPackSettings>
    <MoneyLimit>500</MoneyLimit>
  </MagicWheelPackSettings>
  <DenominationDisplay>
    <SingleDenomination>5</SingleDenomination>
  </DenominationDisplay>
</JurisdictionSettings>
""",
    )
    _write(
        root / "slot" / "themes" / "mgconfig.xml",
        """<?xml version="1.0"?>
<Multigamer>
  <MachineID>GST22377</MachineID>
  <Language>Spanish</Language>
  <JurisdictionSettingsFile>themes\\jurisdiction_config.xml</JurisdictionSettingsFile>
  <InactivitySecondsToGameSelector>300</InactivitySecondsToGameSelector>
  <DefaultBet>Minimum</DefaultBet>
  <ShowAllLines>true</ShowAllLines>
  <ShowDenominationSelector>false</ShowDenominationSelector>
  <NumberOfJackpotCounters>3</NumberOfJackpotCounters>
  <TransferParameters>
    <CashoutButtonMode>Ticket</CashoutButtonMode>
    <PayoutWhenCelebrationLimit>LockAndHandpay</PayoutWhenCelebrationLimit>
  </TransferParameters>
  <DenominationList>
    <int>5</int>
  </DenominationList>
  <CreditRateValues>
    <int>5</int>
  </CreditRateValues>
</Multigamer>
""",
    )
    _write(
        root / "slot" / "themes" / "magicwheel_Config.xml",
        """<?xml version="1.0"?>
<MagicWheelSettingsConfig>
  <Enabled>true</Enabled>
  <Bet>5</Bet>
  <MoneyLimit>500</MoneyLimit>
  <MoneyWheelAverage>25</MoneyWheelAverage>
  <MaxWheelSpins>50000</MaxWheelSpins>
</MagicWheelSettingsConfig>
""",
    )
    _write(
        root / "bios" / "etc" / "application" / "slot" / "oticket.xml",
        """<?xml version="1.0"?>
<OTicket><Enabled>true</Enabled></OTicket>
""",
    )
    _write(
        root / "Services" / "aurum" / "config" / "AurumSetup.xml",
        """<?xml version="1.0"?>
<AurumSetup>
  <CurrencyTable><CurrencyCode>USD</CurrencyCode></CurrencyTable>
  <ProcessorConfig><CurrencyId>USD</CurrencyId></ProcessorConfig>
  <NetworkHostName>GST22377</NetworkHostName>
  <ServiceURI>net.tcp://GST22377:9000/Aurum</ServiceURI>
</AurumSetup>
""",
    )
    _write(
        root / "slot" / "themes" / "BigSafari_HnW" / "MathSettings.xml",
        """<?xml version="1.0"?>
<MathSettings>
  <CurrentReturnPercent>return_94_0</CurrentReturnPercent>
  <FixedBet>7.5</FixedBet>
  <DenomConfig>
    <DenomConfigSettings>
      <DenominationMultiplier>1</DenominationMultiplier>
      <FixedBet>7.5</FixedBet>
      <BetMultipliers>
        <int>4</int>
        <int>8</int>
        <int>12</int>
      </BetMultipliers>
      <ReturnPercent>return_94_0</ReturnPercent>
    </DenomConfigSettings>
  </DenomConfig>
</MathSettings>
""",
    )
    _write(
        root / "Services" / "aurum" / "config" / "SASControler1" / "ClientsSet.xml",
        """<?xml version="1.0"?>
<ClientsSet xmlns="http://tempuri.org/ClientsSet.xsd">
  <Clients>
    <SASClientState>
      <UniqueGMID>GST22377</UniqueGMID>
      <SASAddress>1</SASAddress>
      <AurumEgmId>GCC_ST_GST22377_01</AurumEgmId>
      <AFT.anyAftEnabled>true</AFT.anyAftEnabled>
      <AFT.inHouseTransfersEnabled>true</AFT.inHouseTransfersEnabled>
    </SASClientState>
  </Clients>
</ClientsSet>
""",
    )
    _write(
        root / "Services" / "aurum" / "config" / "SASControler1" / "SASsetupData.xml",
        """<?xml version="1.0"?>
<SASsetupData xmlns="http://tempuri.org/SASsetupData.xsd">
  <FundsTransferType>AFT</FundsTransferType>
  <LockGameWhenNoComms>true</LockGameWhenNoComms>
</SASsetupData>
""",
    )
    (root / "slot" / "OneHand.exe").write_bytes(b"MZ")
    return root


def test_goldclub_root_lifts_slot_folder(tmp_path: Path) -> None:
    root = _fake_goldclub(tmp_path)
    assert goldclub_root_from_target(root / "slot") == root
    assert goldclub_root_from_target(root) == root


def test_read_keyboard_and_bill_protocol(tmp_path: Path) -> None:
    root = _fake_goldclub(tmp_path)
    assert read_keyboard_map(root) == {"261": "Collect", "270": "Spin"}
    assert read_bill_protocol(root) == "JCM"


def test_patch_keyboard_and_bill(tmp_path: Path) -> None:
    root = _fake_goldclub(tmp_path)
    keyboard_src = root / "slot" / "hwdrivers" / "Keyboard.xml"
    keyboard_dest = tmp_path / "Keyboard.xml"
    patch_keyboard_xml(
        keyboard_src, keyboard_dest, {"261": "Collect", "270": "MaxBet", "266": "BetPlus"}
    )
    text = keyboard_dest.read_text(encoding="utf-8")
    assert "MaxBet" in text
    assert 'name="266"' in text

    quixant_src = root / "slot" / "hwdrivers" / "QuixantHardware.xml"
    quixant_dest = tmp_path / "QuixantHardware.xml"
    patch_quixant_bill_protocol(quixant_src, quixant_dest, "MEI")
    text = quixant_dest.read_text(encoding="utf-8")
    assert "<currentProtocol>MEI</currentProtocol>" in text
    assert "<comPortName>COM6</comPortName>" in text
    assert "<Id>MEI</Id>" in text


def test_recipe_roundtrip(tmp_path: Path) -> None:
    recipe = SlotSetupRecipe(
        label="Trinidad test",
        sas=SasSettings(enabled=True, address=3, aft_enabled=False),
        bill_protocol="MEI",
        keyboard={"270": "Spin"},
        bill_tokens=[BillToken(code="97", value=100)],
        math=[
            MathDenomSettings(
                theme="BigSafari_HnW",
                denomination_multiplier=5,
                fixed_bet=1.0,
                bet_multipliers=[1, 2, 4],
                return_percent="return_92_0",
            )
        ],
        denomination_list=[5],
        credit_rate_values=[5],
    )
    path = tmp_path / "recipe.json"
    save_recipe(recipe, path)
    loaded = load_recipe(path)
    assert loaded.label == "Trinidad test"
    assert loaded.sas.address == 3
    assert loaded.sas.validation_controler is True
    assert loaded.door_switches.enabled is True
    assert loaded.bill_protocol == "MEI"
    assert loaded.math[0].bet_multipliers == [1, 2, 4]
    assert "Bill acceptor: MEI" in recipe_summary_lines(loaded)


def test_missing_quixant_does_not_invent_mei(tmp_path: Path) -> None:
    root = _fake_goldclub(tmp_path)
    (root / "slot" / "hwdrivers" / "QuixantHardware.xml").unlink()
    recipe = load_recipe_from_goldclub(root, label="live")
    assert recipe.bill_protocol == ""
    assert recipe.ticket_protocol == ""


def test_load_recipe_from_goldclub(tmp_path: Path) -> None:
    root = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(root, label="live")
    assert recipe.bill_protocol == "JCM"
    assert recipe.ticket_protocol == ""
    assert recipe.keyboard["270"] == "Spin"
    assert recipe.sas.address == 1
    assert recipe.math[0].theme == "BigSafari_HnW"
    assert recipe.denomination_list == [5]
    assert recipe.jurisdiction.tag == "PuertoRico"
    assert recipe.offline_enabled is False
    assert recipe.dallas.code == "0100000000000282"
    assert recipe.mg_identity.language == "Spanish"
    assert recipe.aurum_identity.network_hostname_template == "GST22377"
    assert recipe.jurisdiction.magic_wheel_money_limit == 500
    assert recipe.play_limits.jackpot_counters == 3
    assert recipe.play_limits.jackpot_receipt_layout == "jackpotreceipt0"
    assert recipe.play_limits.celebration_limit == "LockAndHandpay"
    assert recipe.play_limits.magic_wheel_bet == 5
    assert recipe.play_limits.magic_wheel_max_spins == 50000
    assert recipe.door_switches.enabled is True
    assert recipe.door_switches.stacker_installed_auto_unlock is True
    assert recipe.door_switches.all_auto_unlock() is False
    assert recipe.door_switches.auto_unlock_for("cabinet_door") is False


def test_build_and_apply_config_pack(tmp_path: Path) -> None:
    live = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(live, label="pack-test")
    recipe.bill_protocol = "MEI"
    recipe.sas.address = 7
    recipe.keyboard["270"] = "MaxBet"
    recipe.math = [
        MathDenomSettings(
            theme="BigSafari_HnW",
            denomination_multiplier=5,
            fixed_bet=2.0,
            bet_multipliers=[1, 2, 4, 8],
            return_percent="return_92_0",
        )
    ]
    recipe.denomination_list = [5, 10]
    recipe.credit_rate_values = [5, 10]
    recipe.bill_tokens = [
        BillToken(code="97", value=100),
        BillToken(code="99", value=500),
        BillToken(code="100", value=1000),
    ]

    pack = tmp_path / "config-pack"
    built = build_config_pack(recipe, live, pack)
    assert (pack / "recipe.json").is_file()
    assert "slot/hwdrivers/QuixantHardware.xml" in built.files
    assert "slot/hwdrivers/Keyboard.xml" in built.files
    assert any("MathSettings.xml" in f for f in built.files)

    dest = tmp_path / "DestGoldclub"
    # Fresh dest with identity-bearing SAS + empty keyboard tree
    shutil_copy = live
    import shutil

    shutil.copytree(shutil_copy, dest)
    # Change live AurumEgmId on dest so identity merge must keep it
    clients = dest / "Services" / "aurum" / "config" / "SASControler1" / "ClientsSet.xml"
    clients.write_text(
        clients.read_text(encoding="utf-8").replace(
            "GCC_ST_GST22377_01", "GCC_ST_GST99999_01"
        ),
        encoding="utf-8",
    )

    result = apply_config_pack(pack, dest)
    assert not result.errors
    assert "slot/hwdrivers/Keyboard.xml" in result.written
    keyboard = (dest / "slot" / "hwdrivers" / "Keyboard.xml").read_text(encoding="utf-8")
    assert "MaxBet" in keyboard
    quixant = (dest / "slot" / "hwdrivers" / "QuixantHardware.xml").read_text(
        encoding="utf-8"
    )
    assert "<currentProtocol>MEI</currentProtocol>" in quixant
    assert "<comPortName>COM6</comPortName>" in quixant
    clients_text = clients.read_text(encoding="utf-8")
    assert "SASAddress>7</" in clients_text
    # Identity leaf preserved from live dest
    assert "GCC_ST_GST99999_01" in clients_text
    math = (
        dest / "slot" / "themes" / "BigSafari_HnW" / "MathSettings.xml"
    ).read_text(encoding="utf-8")
    assert "<DenominationMultiplier>5</DenominationMultiplier>" in math
    assert "<int>8</int>" in math


def test_apply_skips_serialport_and_licence(tmp_path: Path) -> None:
    live = _fake_goldclub(tmp_path)
    pack = tmp_path / "pack"
    pack.mkdir()
    save_recipe(
        SlotSetupRecipe(
            files=[
                "bios/etc/application/system/hardware/serialport/layout.json",
                "Licenses/dongle.xml",
                "slot/hwdrivers/Keyboard.xml",
            ]
        ),
        pack / "recipe.json",
    )
    # Only keyboard is staged
    src_kb = live / "slot" / "hwdrivers" / "Keyboard.xml"
    dest_kb = pack / "slot" / "hwdrivers" / "Keyboard.xml"
    dest_kb.parent.mkdir(parents=True)
    dest_kb.write_bytes(src_kb.read_bytes())
    (pack / "bios" / "etc" / "application" / "system" / "hardware" / "serialport").mkdir(
        parents=True
    )
    (pack / "bios" / "etc" / "application" / "system" / "hardware" / "serialport" / "layout.json").write_text(
        "{}", encoding="utf-8"
    )
    (pack / "Licenses").mkdir()
    (pack / "Licenses" / "dongle.xml").write_text("<x/>", encoding="utf-8")

    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "slot" / "hwdrivers").mkdir(parents=True)
    result = apply_config_pack(pack, dest)
    assert "slot/hwdrivers/Keyboard.xml" in result.written
    assert any("forbidden" in s for s in result.skipped)
    assert not (dest / "Licenses" / "dongle.xml").exists()
    assert not (
        dest
        / "bios"
        / "etc"
        / "application"
        / "system"
        / "hardware"
        / "serialport"
        / "layout.json"
    ).exists()


def test_phase2_jurisdiction_offline_dallas_placeholders(tmp_path: Path) -> None:
    from config_scanner.slot_setup import (
        AurumIdentitySettings,
        DallasSettings,
        JurisdictionSettings,
        MgIdentitySettings,
    )

    live = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(live, label="phase2")
    recipe.jurisdiction = JurisdictionSettings(
        tag="Trinidad",
        culture_name="en-US",
        currency_name="TTD",
        currency_symbol="$",
        magic_wheel_money_limit=5000,
    )
    recipe.offline_enabled = True
    recipe.include_oticket = True
    recipe.hardware_currency_name = "TTD"
    recipe.dallas = DallasSettings(
        code="01D68A721B000019", unlock=True, group="Service"
    )
    recipe.mg_identity = MgIdentitySettings(
        machine_id_template="GST!!MachineName!!",
        language="English",
        inactivity_seconds_to_game_selector=0,
    )
    recipe.aurum_identity = AurumIdentitySettings(
        network_hostname_template="GST!!MachineName!!"
    )

    pack = tmp_path / "pack2"
    built = build_config_pack(recipe, live, pack)
    assert "slot/themes/jurisdiction_config.xml" in built.files
    assert "slot/themes/HardwareConfig.xml" in built.files
    assert "bios/etc/application/slot/oticket.xml" in built.files
    assert "Services/aurum/config/AurumSetup.xml" in built.files

    jur = (pack / "slot" / "themes" / "jurisdiction_config.xml").read_text(
        encoding="utf-8"
    )
    assert "<Tag>Trinidad</Tag>" in jur
    assert "<CurrencyName>TTD</CurrencyName>" in jur
    assert "<MoneyLimit>5000</MoneyLimit>" in jur

    hw = (pack / "slot" / "themes" / "HardwareConfig.xml").read_text(encoding="utf-8")
    assert "<OfflineEnabled>true</OfflineEnabled>" in hw
    assert "<CurrencyName>TTD</CurrencyName>" in hw
    assert "01D68A721B000019" in hw
    assert "<string>Service</string>" in hw
    assert "IGTKeyAudit" in hw  # other keys preserved

    mg = (pack / "slot" / "themes" / "mgconfig.xml").read_text(encoding="utf-8")
    assert "GST!!MachineName!!" in mg
    assert "<Language>English</Language>" in mg
    assert "<InactivitySecondsToGameSelector>0</InactivitySecondsToGameSelector>" in mg

    aurum = (pack / "Services" / "aurum" / "config" / "AurumSetup.xml").read_text(
        encoding="utf-8"
    )
    assert "<NetworkHostName>GST!!MachineName!!</NetworkHostName>" in aurum
    assert "net.tcp://GST!!MachineName!!:9000/Aurum" in aurum


def test_jackpot_and_magic_wheel_pack(tmp_path: Path) -> None:
    from config_scanner.slot_setup import PlayLimitsSettings

    live = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(live, label="limits")
    recipe.jurisdiction.magic_wheel_money_limit = 5000
    recipe.play_limits = PlayLimitsSettings(
        jackpot_counters=4,
        jackpot_receipt_layout="jackpotreceipt1",
        celebration_limit="Handpay",
        cashout_button_mode="Handpay",
        show_all_lines=False,
        show_denom_selector=True,
        ticket_redeem_enabled=False,
        ticket_use_currency_iso=False,
        default_bet="Maximum",
        magic_wheel_enabled=True,
        magic_wheel_bet=10,
        magic_wheel_max_spins=10000,
        magic_wheel_average=50,
        bet_multipliers=[1, 2, 5, 10],
    )
    pack = tmp_path / "limits-pack"
    built = build_config_pack(recipe, live, pack)
    assert "slot/themes/magicwheel_Config.xml" in built.files
    assert "slot/themes/mgconfig.xml" in built.files
    assert "slot/themes/HardwareConfig.xml" in built.files
    mw = (pack / "slot" / "themes" / "magicwheel_Config.xml").read_text(encoding="utf-8")
    assert "<MoneyLimit>5000</MoneyLimit>" in mw
    assert "<Bet>10</Bet>" in mw
    assert "<MaxWheelSpins>10000</MaxWheelSpins>" in mw
    assert "<MoneyWheelAverage>50</MoneyWheelAverage>" in mw
    mg = (pack / "slot" / "themes" / "mgconfig.xml").read_text(encoding="utf-8")
    assert "<NumberOfJackpotCounters>4</NumberOfJackpotCounters>" in mg
    assert "<CashoutButtonMode>Handpay</CashoutButtonMode>" in mg
    assert "<PayoutWhenCelebrationLimit>Handpay</PayoutWhenCelebrationLimit>" in mg
    assert "<DefaultBet>Maximum</DefaultBet>" in mg
    assert "<ShowDenominationSelector>true</ShowDenominationSelector>" in mg
    hw = (pack / "slot" / "themes" / "HardwareConfig.xml").read_text(encoding="utf-8")
    assert "<LayoutJackpotReceiptTicket>jackpotreceipt1</LayoutJackpotReceiptTicket>" in hw
    assert "<RedeemEnabled>false</RedeemEnabled>" in hw
    math = (
        pack / "slot" / "themes" / "BigSafari_HnW" / "MathSettings.xml"
    ).read_text(encoding="utf-8")
    assert "<int>10</int>" in math
    dest = tmp_path / "applied"
    import shutil

    shutil.copytree(live, dest)
    result = apply_config_pack(pack, dest)
    assert not result.errors
    live_mw = (dest / "slot" / "themes" / "magicwheel_Config.xml").read_text(
        encoding="utf-8"
    )
    assert "<MoneyLimit>5000</MoneyLimit>" in live_mw


_TITO_FUTURE = (
    ".[GoldClub.HW.Subsys.Driver.INodeRoot].[tcp://127.0.0.1:30400]."
    "[GoldClub.HW.Subsys.Driver.TicketPrinter.FutureLogic.PSA66ST2]"
)


def _add_ticket_printer(root: Path, protocol: str = "TRANSACT") -> None:
    quix = root / "slot" / "hwdrivers" / "QuixantHardware.xml"
    text = quix.read_text(encoding="utf-8")
    block = f"""  <TicketPrinter>
    <enable>true</enable>
    <comPortName>COM5</comPortName>
    <currentProtocol>{protocol}</currentProtocol>
  </TicketPrinter>
</root>
"""
    quix.write_text(text.replace("</root>", block), encoding="utf-8")
    _write(
        root
        / "slot"
        / "hwdrivers"
        / "protocols"
        / "ticketprinter"
        / f"TicketPrinter_{protocol}.xml",
        f"""<?xml version="1.0"?>
<TicketPrinterProtocolSettings>
  <Protocol>{protocol}</Protocol>
</TicketPrinterProtocolSettings>
""",
    )


def _write_driverssetup(root: Path, driver_raw: str) -> None:
    _write(
        root
        / "bios"
        / "etc"
        / "application"
        / "HW"
        / "driverssetup"
        / "configuration.xml",
        f"""<?xml version="1.0" encoding="utf-8"?>
<config xmlns="config">
  <drivers>
    <item0>
      <aliasName>tito</aliasName>
      <driverRawName>{driver_raw}</driverRawName>
      <enabled>True</enabled>
      <options>
        <endpointaddress>tcp://127.0.0.1:30400</endpointaddress>
      </options>
    </item0>
  </drivers>
</config>
""",
    )


def test_ticket_protocol_from_hw_driver_names() -> None:
    assert ticket_protocol_from_hw_driver(_TITO_FUTURE) == "JCM"
    assert (
        ticket_protocol_from_hw_driver(
            ".[GoldClub.HW.Subsys.Driver.TicketPrinter.Ithaca.Epic950]"
        )
        == "TRANSACT"
    )
    assert (
        ticket_protocol_from_hw_driver(
            ".[GoldClub.HW.Subsys.Driver.FutureLogic.PSA66ST2]"
        )
        == "JCM"
    )


def test_ticket_protocol_hwsetup_wins_over_quixant(tmp_path: Path) -> None:
    root = _fake_goldclub(tmp_path)
    _add_ticket_printer(root, "TRANSACT")
    _write_driverssetup(root, _TITO_FUTURE)
    assert read_ticket_protocol(root) == "JCM"
    recipe = load_recipe_from_goldclub(root, label="live")
    assert recipe.ticket_protocol == "JCM"


def test_ticket_protocol_from_quixant_when_no_hwsetup(tmp_path: Path) -> None:
    root = _fake_goldclub(tmp_path)
    _add_ticket_printer(root, "TRANSACT")
    assert read_ticket_protocol(root) == "TRANSACT"


def test_ticket_protocol_pack_switches_hwsetup_and_quixant(tmp_path: Path) -> None:
    live = _fake_goldclub(tmp_path)
    _add_ticket_printer(live, "JCM")
    _write(
        live
        / "slot"
        / "hwdrivers"
        / "protocols"
        / "ticketprinter"
        / "TicketPrinter_TRANSACT.xml",
        """<?xml version="1.0"?>
<TicketPrinterProtocolSettings>
  <Protocol>TRANSACT</Protocol>
</TicketPrinterProtocolSettings>
""",
    )
    _write_driverssetup(live, _TITO_FUTURE)
    recipe = load_recipe_from_goldclub(live, label="pack-ticket")
    assert recipe.ticket_protocol == "JCM"
    recipe.ticket_protocol = "TRANSACT"

    pack = tmp_path / "config-pack"
    built = build_config_pack(recipe, live, pack)
    assert "slot/hwdrivers/QuixantHardware.xml" in built.files
    hw_rel = "bios/etc/application/HW/driverssetup/configuration.xml"
    assert hw_rel in built.files

    dest = tmp_path / "DestGoldclub"
    import shutil

    shutil.copytree(live, dest)
    result = apply_config_pack(pack, dest)
    assert not result.errors
    quixant = (dest / "slot" / "hwdrivers" / "QuixantHardware.xml").read_text(
        encoding="utf-8"
    )
    assert "<currentProtocol>TRANSACT</currentProtocol>" in quixant
    assert "<comPortName>COM5</comPortName>" in quixant
    hw = (
        dest
        / "bios"
        / "etc"
        / "application"
        / "HW"
        / "driverssetup"
        / "configuration.xml"
    ).read_text(encoding="utf-8")
    assert TICKET_HW_DRIVER["TRANSACT"] in hw
    assert "tcp://127.0.0.1:30400" in hw
    assert 'xmlns="config"' in hw
    assert "ns0:" not in hw
    dest_patch = tmp_path / "tito-out.xml"
    patch_tito_ticket_driver(
        dest / "bios" / "etc" / "application" / "HW" / "driverssetup" / "configuration.xml",
        dest_patch,
        "JCM",
    )
    back = dest_patch.read_text(encoding="utf-8")
    assert TICKET_HW_DRIVER["JCM"] in back
    assert "tcp://127.0.0.1:30400" in back


def test_mei_bill_token_issues_flags_missing_98_and_code_103() -> None:
    broken = [
        BillToken(code="97", value=100),
        BillToken(code="99", value=500),
        BillToken(code="103", value=10000),
    ]
    issues = mei_bill_token_issues(broken)
    assert any("98" in i for i in issues)
    assert any("103" in i for i in issues)


def test_normalize_mei_bill_tokens_ttd_replaces_broken_layout() -> None:
    broken = [
        BillToken(code="97", value=100),
        BillToken(code="99", value=500),
        BillToken(code="103", value=10000),
    ]
    fixed = normalize_mei_bill_tokens_for_currency(broken, "TTD")
    assert [t.code for t in fixed] == [t.code for t in TTD_MEI_BILL_TOKENS]
    assert fixed[1].value == 500


def test_default_bill_tokens_for_ttd_matches_cs_pack() -> None:
    tokens = default_bill_tokens_for_currency("TTD")
    assert len(tokens) == 6
    assert tokens[0].code == "97" and tokens[0].value == 100
    assert tokens[-1].code == "102" and tokens[-1].value == 10000


def test_patch_hardware_config_writes_ttd_mei_bill_codes(tmp_path: Path) -> None:
    src = tmp_path / "HardwareConfig.xml"
    src.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<HardwareSettings>
  <BillSettings><Bills>
    <TokenMapping Code="97">100</TokenMapping>
    <TokenMapping Code="103">10000</TokenMapping>
  </Bills></BillSettings>
</HardwareSettings>""",
        encoding="utf-8",
    )
    dest_dir = tmp_path / "slot" / "themes"
    dest_dir.mkdir(parents=True)
    dest = dest_dir / "HardwareConfig.xml"
    patch_hardware_config(src, dest, tokens=list(TTD_MEI_BILL_TOKENS))
    text = dest.read_text(encoding="utf-8")
    assert 'Code="98"' in text
    assert 'Code="103"' not in text
    tokens = read_bill_tokens(tmp_path)
    assert [t.code for t in tokens] == [t.code for t in TTD_MEI_BILL_TOKENS]


def test_patch_hardware_config_writes_can_accept_false(tmp_path: Path) -> None:
    src = tmp_path / "HardwareConfig.xml"
    src.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<HardwareSettings>
  <BillSettings><Bills>
    <TokenMapping Code="97" CanAccept="true" CanReturn="true">100</TokenMapping>
  </Bills></BillSettings>
</HardwareSettings>""",
        encoding="utf-8",
    )
    dest_dir = tmp_path / "slot" / "themes"
    dest_dir.mkdir(parents=True)
    dest = dest_dir / "HardwareConfig.xml"
    patch_hardware_config(
        src,
        dest,
        tokens=[BillToken(code="97", value=100, can_accept=False)],
    )
    tokens = read_bill_tokens(tmp_path)
    assert len(tokens) == 1
    assert tokens[0].can_accept is False
    assert 'CanAccept="false"' in dest.read_text(encoding="utf-8")


def test_math_theme_names_skips_roulette_and_feature_folders(tmp_path: Path) -> None:
    from config_scanner.slot_setup import _math_theme_names

    themes = tmp_path / "slot" / "themes"
    for name in (
        "BigSafari_HnW",
        "RouletteGame",
        "Link2WinFeature",
        "_RouletteGame_disabled",
        "data",
    ):
        d = themes / name
        d.mkdir(parents=True)
        if name not in {"data", "Link2WinFeature"}:
            (d / "MathSettings.xml").write_text("<math/>", encoding="utf-8")
    (themes / "Link2WinFeature" / "Link2WinBonusMath.json").write_bytes(b"\x00")
    assert _math_theme_names(tmp_path) == ["BigSafari_HnW"]


def test_jurisdiction_currency_base_uses_ascii_c_not_utf8_cent() -> None:
    from config_scanner.machine_identity import postprocess_jurisdiction_xml_bytes

    raw = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<Jurisdiction><CurrencyDisplaySettings>"
        "<CurrencyBaseSymbol>\u00a2</CurrencyBaseSymbol>"
        "<CurrencyDisplayFormat>"
        "<CurrencyBaseFormat>{0}\u00a2</CurrencyBaseFormat>"
        "</CurrencyDisplayFormat></CurrencyDisplaySettings></Jurisdiction>"
    ).encode("utf-8")
    fixed = postprocess_jurisdiction_xml_bytes(raw).decode("utf-8")
    assert "<CurrencyBaseSymbol>c</CurrencyBaseSymbol>" in fixed
    assert "<CurrencyBaseFormat>{0}c</CurrencyBaseFormat>" in fixed
    assert "\u00a2" not in fixed
    assert b"\xc2\xa2" not in postprocess_jurisdiction_xml_bytes(raw)


def test_merge_jurisdiction_strips_cent_without_identity_change() -> None:
    from config_scanner.machine_identity import merge_xml_bytes_preserving_identity

    incoming = (
        b'<?xml version="1.0"?>'
        b"<JurisdictionSettings><CurrencyDisplaySettings>"
        b"<CurrencyBaseSymbol>\xc2\xa2</CurrencyBaseSymbol>"
        b"<CurrencyBaseFormat>{0}\xc2\xa2</CurrencyBaseFormat>"
        b"</CurrencyDisplaySettings></JurisdictionSettings>"
    )
    merged = merge_xml_bytes_preserving_identity(
        incoming,
        incoming,
        relative_path="slot/themes/jurisdiction_config.xml",
    )
    assert b"\xc2\xa2" not in merged
    assert b">c</CurrencyBaseSymbol>" in merged
    assert b">{0}c</CurrencyBaseFormat>" in merged


def test_prepare_restore_jurisdiction_without_live_file(tmp_path: Path) -> None:
    from config_scanner.machine_identity import prepare_restore_bytes_preserving_identity

    dest = tmp_path / "slot" / "themes" / "jurisdiction_config.xml"
    incoming = (
        b'<?xml version="1.0"?>'
        b"<JurisdictionSettings><CurrencyDisplaySettings>"
        b"<CurrencyBaseSymbol>\xc2\xa2</CurrencyBaseSymbol>"
        b"</CurrencyDisplaySettings></JurisdictionSettings>"
    )
    out = prepare_restore_bytes_preserving_identity(
        dest, incoming, "slot/themes/jurisdiction_config.xml"
    )
    assert b"\xc2\xa2" not in out
    assert b">c</CurrencyBaseSymbol>" in out


def test_normalize_jurisdiction_apply_value_cent_to_c() -> None:
    from config_scanner.machine_identity import normalize_jurisdiction_apply_value

    assert (
        normalize_jurisdiction_apply_value(
            "CurrencyDisplaySettings/CurrencyBaseSymbol", "\u00a2"
        )
        == "c"
    )


def test_normalize_jurisdiction_apply_value_rejects_non_ascii_symbol() -> None:
    import pytest

    from config_scanner.machine_identity import normalize_jurisdiction_apply_value

    with pytest.raises(ValueError, match="ASCII"):
        normalize_jurisdiction_apply_value(
            "CurrencyDisplaySettings/CurrencyBaseSymbol", "\u20ac"
        )


def test_apply_xml_jurisdiction_cent_normalized(tmp_path: Path) -> None:
    from config_scanner.xml_diff import apply_xml_value_at_path

    jur = tmp_path / "jurisdiction_config.xml"
    jur.write_text(
        '<?xml version="1.0"?><JurisdictionSettings>'
        "<CurrencyDisplaySettings>"
        "<CurrencyBaseSymbol>OLD</CurrencyBaseSymbol>"
        "<CurrencyBaseFormat>{0}OLD</CurrencyBaseFormat>"
        "</CurrencyDisplaySettings></JurisdictionSettings>",
        encoding="utf-8",
    )
    apply_xml_value_at_path(
        jur, "CurrencyDisplaySettings/CurrencyBaseSymbol", "\u00a2"
    )
    text = jur.read_text(encoding="utf-8")
    assert "<CurrencyBaseSymbol>c</CurrencyBaseSymbol>" in text
    assert "\u00a2" not in text
    assert b"\xc2\xa2" not in jur.read_bytes()


def test_leftover_single_denomination_detected(tmp_path: Path) -> None:
    from config_scanner.slot_setup import (
        leftover_jurisdiction_single_denomination,
        read_jurisdiction_single_denomination,
    )

    live = _fake_goldclub(tmp_path)
    mg = live / "slot" / "themes" / "mgconfig.xml"
    mg.write_text(
        mg.read_text(encoding="utf-8").replace("<int>5</int>", "<int>10</int>"),
        encoding="utf-8",
    )
    assert read_jurisdiction_single_denomination(live) == 5
    assert leftover_jurisdiction_single_denomination(live, [10]) == 5
    assert leftover_jurisdiction_single_denomination(live, [5]) is None


def test_build_pack_writes_jurisdiction_single_denomination(tmp_path: Path) -> None:
    live = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(live, label="denom")
    recipe.denomination_list = [10]
    recipe.credit_rate_values = [10]
    pack = tmp_path / "pack-denom"
    built = build_config_pack(
        recipe, live, pack, sections=frozenset({"mgconfig", "jurisdiction"})
    )
    assert "slot/themes/jurisdiction_config.xml" in built.files
    jur = (pack / "slot" / "themes" / "jurisdiction_config.xml").read_text(
        encoding="utf-8"
    )
    assert "<SingleDenomination>10</SingleDenomination>" in jur


def test_sas_channel_flags_follow_aurum_owner_host(tmp_path: Path) -> None:
    from config_scanner.slot_setup import (
        patch_aurum_setup_placeholders,
        read_sas_channel_flags,
        AurumIdentitySettings,
    )

    live = _fake_goldclub(tmp_path)
    src = live / "Services" / "aurum" / "config" / "AurumSetup.xml"
    src.write_text(
        """<?xml version="1.0"?>
<AurumSetup>
  <Network>
    <Configs>
      <Subscribers>
        <HostId>1</HostId>
        <HostName>SASControler1</HostName>
      </Subscribers>
      <EgmsDevices>
        <DeviceClass>voucher</DeviceClass>
        <OwnerHostId>1</OwnerHostId>
        <LastConfigurationChange>4</LastConfigurationChange>
      </EgmsDevices>
      <EgmsDevices>
        <DeviceClass>WAT</DeviceClass>
        <OwnerHostId>1</OwnerHostId>
        <LastConfigurationChange>4</LastConfigurationChange>
      </EgmsDevices>
      <EgmsDevices>
        <DeviceClass>handpay</DeviceClass>
        <OwnerHostId>1</OwnerHostId>
        <LastConfigurationChange>4</LastConfigurationChange>
      </EgmsDevices>
      <EgmsDevices>
        <DeviceClass>bonus</DeviceClass>
        <OwnerHostId>0</OwnerHostId>
        <LastConfigurationChange>4</LastConfigurationChange>
      </EgmsDevices>
      <EgmsDevices>
        <DeviceClass>noteAcceptor</DeviceClass>
        <OwnerHostId>1</OwnerHostId>
        <LastConfigurationChange>4</LastConfigurationChange>
      </EgmsDevices>
    </Configs>
  </Network>
</AurumSetup>
""",
        encoding="utf-8",
    )
    flags = read_sas_channel_flags(live)
    assert flags["validation_controler"] is True
    assert flags["cashless_controler"] is True
    assert flags["bonusing_controler"] is False
    recipe = load_recipe_from_goldclub(live)
    assert recipe.sas.bonusing_controler is False
    recipe.sas.bonusing_controler = True
    recipe.sas.note_acceptor_controler = False
    dest = tmp_path / "AurumSetup.out.xml"
    patch_aurum_setup_placeholders(
        src, dest, AurumIdentitySettings(), sas=recipe.sas
    )
    text = dest.read_text(encoding="utf-8")
    assert text.count("<DeviceClass>bonus</DeviceClass>") == 1
    assert "<OwnerHostId>1</OwnerHostId>" in text
    patched = dest.read_text(encoding="utf-8")
    # note acceptor released from SAS; bonus now owned
    live2 = tmp_path / "gold2"
    (live2 / "Services" / "aurum" / "config").mkdir(parents=True)
    (live2 / "Services" / "aurum" / "config" / "AurumSetup.xml").write_text(
        patched, encoding="utf-8"
    )
    out = read_sas_channel_flags(live2)
    assert out["bonusing_controler"] is True
    assert out["note_acceptor_controler"] is False


def test_door_switches_roundtrip_hardware_config(tmp_path: Path) -> None:
    from config_scanner.slot_setup import (
        DoorSwitchRow,
        DoorSwitchSettings,
        patch_hardware_config,
        read_door_switches,
    )

    live = _fake_goldclub(tmp_path)
    hw = live / "slot" / "themes" / "HardwareConfig.xml"
    src = hw.read_text(encoding="utf-8")
    hw.write_text(
        src.replace(
            "</HardwareSettings>",
            """  <SwitchesSettings>
    <Enabled>true</Enabled>
    <SwitchSettingsList>
      <SwitchSettings SwitchName="cabinet_door" AlertType="BOTH" AutoUnlock="true" OfflineTriggerAutoUnlock="false" />
      <SwitchSettings SwitchName="logic_door" AlertType="SEMAPHORE" AutoUnlock="false" OfflineTriggerAutoUnlock="false" />
    </SwitchSettingsList>
  </SwitchesSettings>
</HardwareSettings>
""",
        ),
        encoding="utf-8",
    )
    settings = read_door_switches(live)
    assert settings.enabled is True
    assert settings.stacker_installed_auto_unlock is True
    assert settings.items[0].name == "cabinet_door"
    assert settings.items[0].alert_type == "BOTH"
    assert settings.items[0].auto_unlock is True
    assert settings.auto_unlock_for("logic_door") is False
    recipe = load_recipe_from_goldclub(live)
    assert recipe.door_switches.items[0].auto_unlock is True
    dest = tmp_path / "HardwareConfig.out.xml"
    patch_hardware_config(
        hw,
        dest,
        door_switches=DoorSwitchSettings(
            enabled=False,
            items=[
                DoorSwitchRow(
                    name="cabinet_door",
                    alert_type="SEMAPHORE",
                    auto_unlock=False,
                    offline_trigger=True,
                )
            ],
        ),
    )
    text = dest.read_text(encoding="utf-8")
    assert "<Enabled>false</Enabled>" in text
    assert 'SwitchName="cabinet_door"' in text
    assert 'AlertType="SEMAPHORE"' in text
    assert 'OfflineTriggerAutoUnlock="true"' in text


def test_is_debug_onehand_version_token() -> None:
    from config_scanner.slot_setup import is_debug_onehand_version

    assert is_debug_onehand_version("Debug")
    assert is_debug_onehand_version("DEBUG")
    assert is_debug_onehand_version("2.0.1 Debug")
    assert not is_debug_onehand_version("2.0.1")
    assert not is_debug_onehand_version("")
    assert not is_debug_onehand_version(None)


def test_is_onehand_debug_build_from_pe_product_version(tmp_path: Path) -> None:
    from config_scanner.slot_setup import is_onehand_debug_build

    gold = _fake_goldclub(tmp_path)
    exe = gold / "slot" / "OneHand.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ" + "ProductVersion\0Debug\0".encode("utf-16le"))
    assert is_onehand_debug_build(gold) is True

    exe.write_bytes(b"MZ" + "ProductVersion\0" "2.0.1\0".encode("utf-16le"))
    assert is_onehand_debug_build(gold) is False


def test_is_onehand_debug_build_ignores_earlier_numeric_then_finds_debug(
    tmp_path: Path,
) -> None:
    from config_scanner.slot_setup import is_onehand_debug_build

    gold = _fake_goldclub(tmp_path)
    exe = gold / "slot" / "OneHand.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(
        b"MZ"
        + "ProductVersion\0".encode("utf-16le")
        + "3.0.0.0+RC2+2667F2\0".encode("utf-16le")
        + b"\x00" * (5 * 1024 * 1024)
        + "FileVersion\0".encode("utf-16le")
        + "Debug\0".encode("utf-16le")
    )
    assert is_onehand_debug_build(gold) is True


def test_is_onehand_debug_build_v3_rc_hex_without_debug_word(tmp_path: Path) -> None:
    from config_scanner.slot_setup import is_onehand_debug_build

    gold = _fake_goldclub(tmp_path)
    exe = gold / "slot" / "OneHand.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(
        b"MZ"
        + "ProductVersion\0".encode("utf-16le")
        + "3.0.0.0+RC2+2667F2\0".encode("utf-16le")
        + "AssemblyConfiguration\0".encode("utf-16le")
        + "Release\0".encode("utf-16le")
    )
    assert is_onehand_debug_build(gold) is True


def test_is_onehand_debug_build_from_filename(tmp_path: Path) -> None:
    from config_scanner.slot_setup import is_onehand_debug_build

    gold = _fake_goldclub(tmp_path)
    (gold / "slot" / "OneHand.exe").write_bytes(b"MZ")
    assert is_onehand_debug_build(gold) is False


def test_licence_push_default_checked_skips_debug() -> None:
    from config_scanner.slot_setup import licence_push_default_checked

    assert (
        licence_push_default_checked(
            needs_push=True, can_mirror=True, has_source=True, debug_onehand=True
        )
        is False
    )
    assert (
        licence_push_default_checked(
            needs_push=True, can_mirror=False, has_source=True, debug_onehand=False
        )
        is True
    )
    assert (
        licence_push_default_checked(
            needs_push=True, can_mirror=True, has_source=False, debug_onehand=False
        )
        is True
    )
    assert (
        licence_push_default_checked(
            needs_push=False, can_mirror=True, has_source=True, debug_onehand=False
        )
        is False
    )


def test_sas_address_pack_does_not_rewrite_aurum_setup(tmp_path: Path) -> None:
    from config_scanner.slot_setup import patch_clients_set, sas_channel_flags_differ

    live = _fake_goldclub(tmp_path)
    original = (live / "Services" / "aurum" / "config" / "AurumSetup.xml").read_bytes()
    recipe = load_recipe_from_goldclub(live, label="sas-addr")
    assert not sas_channel_flags_differ(live, recipe.sas)
    recipe.sas.address = 9
    pack = tmp_path / "sas-only"
    built = build_config_pack(recipe, live, pack, sections=frozenset({"sas"}))
    files = {f.replace("\\", "/").casefold() for f in built.files}
    assert not any(name.endswith("aurumsetup.xml") for name in files)
    assert any("clientsset.xml" in name for name in files)
    assert any("sassetupdata.xml" in name for name in files)
    assert (live / "Services" / "aurum" / "config" / "AurumSetup.xml").read_bytes() == original

    dest = tmp_path / "clients-out.xml"
    patch_clients_set(
        live / "Services" / "aurum" / "config" / "SASControler1" / "ClientsSet.xml",
        dest,
        recipe.sas,
    )
    text = dest.read_text(encoding="utf-8")
    assert 'xmlns="http://tempuri.org/ClientsSet.xsd"' in text
    assert "ns0:" not in text
    assert "SASAddress>9</" in text


def test_sas_channel_pack_still_stages_aurum_setup(tmp_path: Path) -> None:
    from config_scanner.slot_setup import (
        AurumIdentitySettings,
        patch_aurum_setup_placeholders,
        sas_channel_flags_differ,
    )

    live = _fake_goldclub(tmp_path)
    src = live / "Services" / "aurum" / "config" / "AurumSetup.xml"
    src.write_text(
        """<?xml version="1.0"?>
<AurumSetup>
  <Network>
    <Configs>
      <Subscribers>
        <HostId>1</HostId>
        <HostName>SASControler1</HostName>
      </Subscribers>
      <EgmsDevices>
        <DeviceClass>bonus</DeviceClass>
        <OwnerHostId>0</OwnerHostId>
        <LastConfigurationChange>4</LastConfigurationChange>
      </EgmsDevices>
    </Configs>
  </Network>
</AurumSetup>
""",
        encoding="utf-8",
    )
    recipe = load_recipe_from_goldclub(live, label="ch")
    assert recipe.sas.bonusing_controler is False
    recipe.sas.bonusing_controler = True
    assert sas_channel_flags_differ(live, recipe.sas)
    pack = tmp_path / "sas-ch"
    built = build_config_pack(recipe, live, pack, sections=frozenset({"sas"}))
    files = {f.replace("\\", "/").casefold() for f in built.files}
    assert any(name.endswith("aurumsetup.xml") for name in files)
    out = tmp_path / "ch.xml"
    patch_aurum_setup_placeholders(
        src, out, AurumIdentitySettings(), sas=recipe.sas
    )
    assert "<OwnerHostId>1</OwnerHostId>" in out.read_text(encoding="utf-8")
