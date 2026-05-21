"""Tests for Linux BlueZ key reading."""

from pathlib import Path

import pytest

from bluetooth_dualboot.linux_bt import discover_ble_devices, read_ble_keys

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
