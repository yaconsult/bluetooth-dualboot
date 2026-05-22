"""Tests for Linux BlueZ key reading."""

from pathlib import Path

import pytest

from bluetooth_dualboot.linux_bt import (
    BLEKeys,
    ClassicKeys,
    discover_all_devices,
    discover_ble_devices,
    patch_ble_info_file,
    read_ble_keys,
    read_classic_keys,
)

BLE_INFO = """\
[General]
Name=BT5.0 Mouse
Appearance=0x03c2
AddressType=static
SupportedTechnologies=LE;
Trusted=true
Blocked=false

[IdentityResolvingKey]
Key=9CA8DC498406FE2496D9355156612611

[LongTermKey]
Key=6AA1ACBA40F3DDB60C78FA7C3B23A709
Authenticated=0
EncSize=16
EDiv=36159
Rand=4383710011340050161

[PeripheralLongTermKey]
Key=D10DB5CA0A3C98CDAC49A229A41E3406
Authenticated=0
EncSize=16
EDiv=19232
Rand=4284274170293064201

[LocalSignatureKey]
Key=8FBD1BD151ED14DD8508EF1F87677A96
Counter=0
Authenticated=false

[RemoteSignatureKey]
Key=8CF9AB0A68AFF9D2562F406B812DAB1C
Counter=0
Authenticated=false
"""

CLASSIC_INFO = """\
[General]
Name=Baseus BA01
Class=0x240404
SupportedTechnologies=BR/EDR;
Trusted=true

[LinkKey]
Key=AF34A492D9CA9CA11330C4FC4D8475E3
Type=4
PINLength=0
"""


def _write_info(tmp_path: Path, content: str) -> Path:
    info = tmp_path / "info"
    info.write_text(content)
    return info


def test_read_ble_keys_ble_device(tmp_path):
    info = _write_info(tmp_path, BLE_INFO)
    keys = read_ble_keys(info, "C0:35:32:AC:13:4A", "E4:9F:64:0B:E8:1C")
    assert keys is not None
    assert keys.device_name == "BT5.0 Mouse"
    assert keys.ltk == "6AA1ACBA40F3DDB60C78FA7C3B23A709"
    assert keys.irk == "9CA8DC498406FE2496D9355156612611"
    assert keys.ltk_ediv == 36159
    assert keys.ltk_rand == 4383710011340050161
    assert keys.csrk_local == "8FBD1BD151ED14DD8508EF1F87677A96"
    assert keys.csrk_remote == "8CF9AB0A68AFF9D2562F406B812DAB1C"


def test_read_ble_keys_classic_device_returns_none(tmp_path):
    info = _write_info(tmp_path, CLASSIC_INFO)
    keys = read_ble_keys(info, "C0:35:32:AC:13:4A", "DF:D6:4F:C9:DC:97")
    assert keys is None


def test_discover_ble_devices(tmp_path):
    # Build a fake BlueZ directory structure
    adapter_dir = tmp_path / "C0:35:32:AC:13:4A"
    ble_device_dir = adapter_dir / "E4:9F:64:0B:E8:1C"
    classic_device_dir = adapter_dir / "DF:D6:4F:C9:DC:97"
    ble_device_dir.mkdir(parents=True)
    classic_device_dir.mkdir(parents=True)
    (ble_device_dir / "info").write_text(BLE_INFO)
    (classic_device_dir / "info").write_text(CLASSIC_INFO)
    (tmp_path / "mesh").mkdir()  # should be ignored

    devices = discover_ble_devices(tmp_path)
    assert len(devices) == 1
    assert devices[0].device_mac == "E4:9F:64:0B:E8:1C"
    assert devices[0].device_name == "BT5.0 Mouse"


def test_discover_ble_devices_missing_dir():
    with pytest.raises(FileNotFoundError):
        discover_ble_devices(Path("/nonexistent/path"))


def test_read_classic_keys(tmp_path):
    info = _write_info(tmp_path, CLASSIC_INFO)
    keys = read_classic_keys(info, "C0:35:32:AC:13:4A", "DF:D6:4F:C9:DC:97")
    assert keys is not None
    assert isinstance(keys, ClassicKeys)
    assert keys.device_name == "Baseus BA01"
    assert keys.link_key == "AF34A492D9CA9CA11330C4FC4D8475E3"
    assert keys.link_key_type == 4
    assert keys.pin_length == 0


def test_read_classic_keys_ble_returns_none(tmp_path):
    info = _write_info(tmp_path, BLE_INFO)
    keys = read_classic_keys(info, "C0:35:32:AC:13:4A", "E4:9F:64:0B:E8:1C")
    assert keys is None


def test_discover_all_devices(tmp_path):
    adapter_dir = tmp_path / "C0:35:32:AC:13:4A"
    ble_device_dir = adapter_dir / "E4:9F:64:0B:E8:1C"
    classic_device_dir = adapter_dir / "DF:D6:4F:C9:DC:97"
    ble_device_dir.mkdir(parents=True)
    classic_device_dir.mkdir(parents=True)
    (ble_device_dir / "info").write_text(BLE_INFO)
    (classic_device_dir / "info").write_text(CLASSIC_INFO)
    (tmp_path / "mesh").mkdir()  # should be ignored

    devices = discover_all_devices(tmp_path)
    assert len(devices) == 2
    ble = [d for d in devices if isinstance(d, BLEKeys)]
    classic = [d for d in devices if isinstance(d, ClassicKeys)]
    assert len(ble) == 1
    assert len(classic) == 1
    assert ble[0].device_name == "BT5.0 Mouse"
    assert classic[0].device_name == "Baseus BA01"


def test_discover_all_devices_missing_dir():
    with pytest.raises(FileNotFoundError):
        discover_all_devices(Path("/nonexistent/path"))


def test_patch_ble_info_file_updates_keys(tmp_path):
    """patch_ble_info_file should overwrite LTK, IRK, CSRK and LTK params."""
    info = _write_info(tmp_path, BLE_INFO)
    patch_ble_info_file(
        info_path=info,
        ltk="AABBCCDDEEFF00112233445566778899",
        ltk_rand=9999,
        ltk_ediv=1234,
        irk="11223344556677889900AABBCCDDEEFF",
        csrk_local="LOCALCSRK0000000000000000000000AA",
        csrk_remote="REMOTCSRK0000000000000000000000BB",
    )
    keys = read_ble_keys(info, "C0:35:32:AC:13:4A", "E4:9F:64:0B:E8:1C")
    assert keys is not None
    assert keys.ltk == "AABBCCDDEEFF00112233445566778899"
    assert keys.ltk_ediv == 1234
    assert keys.ltk_rand == 9999
    assert keys.irk == "11223344556677889900AABBCCDDEEFF"
    assert keys.csrk_local == "LOCALCSRK0000000000000000000000AA"
    assert keys.csrk_remote == "REMOTCSRK0000000000000000000000BB"


def test_patch_ble_info_file_preserves_general(tmp_path):
    """patch_ble_info_file should preserve [General] and other metadata."""
    info = _write_info(tmp_path, BLE_INFO)
    patch_ble_info_file(
        info_path=info,
        ltk="AABBCCDDEEFF00112233445566778899",
        ltk_rand=9999,
        ltk_ediv=1234,
        irk="11223344556677889900AABBCCDDEEFF",
    )
    keys = read_ble_keys(info, "C0:35:32:AC:13:4A", "E4:9F:64:0B:E8:1C")
    assert keys is not None
    assert keys.device_name == "BT5.0 Mouse"
    assert keys.address_type == "static"


def test_patch_ble_info_file_updates_peripheral_and_slave_ltk(tmp_path):
    """patch_ble_info_file should update PeripheralLongTermKey and SlaveLongTermKey."""
    info = _write_info(tmp_path, BLE_INFO)
    patch_ble_info_file(
        info_path=info,
        ltk="AABBCCDDEEFF00112233445566778899",
        ltk_rand=9999,
        ltk_ediv=1234,
        irk="11223344556677889900AABBCCDDEEFF",
        peripheral_ltk="AABBCCDDEEFF00112233445566778899",
        peripheral_ltk_rand=9999,
        peripheral_ltk_ediv=1234,
    )
    keys = read_ble_keys(info, "C0:35:32:AC:13:4A", "E4:9F:64:0B:E8:1C")
    assert keys is not None
    assert keys.peripheral_ltk == "AABBCCDDEEFF00112233445566778899"
    assert keys.peripheral_ltk_ediv == 1234
    assert keys.peripheral_ltk_rand == 9999
    # SlaveLongTermKey should also be written (read manually since BLEKeys doesn't parse it)
    import configparser

    parser = configparser.ConfigParser()
    parser.read(str(info))
    assert "SlaveLongTermKey" in parser
    assert parser["SlaveLongTermKey"]["Key"] == "AABBCCDDEEFF00112233445566778899"


def test_patch_ble_info_file_creates_missing_sections(tmp_path):
    """patch_ble_info_file creates sections that don't exist yet."""
    # Minimal BLE info with no key sections
    minimal_info = """\
[General]
Name=Test Device
AddressType=static
SupportedTechnologies=LE;
Trusted=true
Blocked=false
"""
    info = _write_info(tmp_path, minimal_info)
    patch_ble_info_file(
        info_path=info,
        ltk="AABBCCDDEEFF00112233445566778899",
        ltk_rand=9999,
        ltk_ediv=1234,
        irk="11223344556677889900AABBCCDDEEFF",
        csrk_local="LOCALCSRK0000000000000000000000AA",
        csrk_remote="REMOTCSRK0000000000000000000000BB",
    )
    keys = read_ble_keys(info, "AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66")
    assert keys is not None
    assert keys.ltk == "AABBCCDDEEFF00112233445566778899"
    assert keys.irk == "11223344556677889900AABBCCDDEEFF"
    assert keys.csrk_local == "LOCALCSRK0000000000000000000000AA"
    assert keys.csrk_remote == "REMOTCSRK0000000000000000000000BB"
