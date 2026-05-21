"""Read Bluetooth device pairing keys from the Linux BlueZ key store."""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

BLUEZ_BASE = Path("/var/lib/bluetooth")


@dataclass
class BLEKeys:
    """BLE pairing keys for a single device as stored by BlueZ."""

    device_mac: str
    adapter_mac: str
    device_name: str

    ltk: str = ""
    ltk_authenticated: int = 0
    ltk_enc_size: int = 16
    ltk_ediv: int = 0
    ltk_rand: int = 0

    peripheral_ltk: str = ""
    peripheral_ltk_authenticated: int = 0
    peripheral_ltk_enc_size: int = 16
    peripheral_ltk_ediv: int = 0
    peripheral_ltk_rand: int = 0

    irk: str = ""

    csrk_local: str = ""
    csrk_local_counter: int = 0
    csrk_remote: str = ""
    csrk_remote_counter: int = 0

    address_type: str = "static"
    extra: dict = field(default_factory=dict)


def _read_info_file(path: Path) -> configparser.ConfigParser:
    """Parse a BlueZ device info file (INI-style)."""
    parser = configparser.ConfigParser()
    parser.read(str(path))
    return parser


def read_ble_keys(info_path: Path, adapter_mac: str, device_mac: str) -> BLEKeys | None:
    """Parse a BlueZ info file and return BLEKeys if it is a BLE device, else None."""
    parser = _read_info_file(info_path)

    general = parser["General"] if "General" in parser else {}
    technologies = general.get("SupportedTechnologies", "")

    if "LE" not in technologies:
        return None

    keys = BLEKeys(
        device_mac=device_mac,
        adapter_mac=adapter_mac,
        device_name=general.get("Name", "Unknown"),
        address_type=general.get("AddressType", "static"),
    )

    if "LongTermKey" in parser:
        ltk_sec = parser["LongTermKey"]
        keys.ltk = ltk_sec.get("Key", "")
        keys.ltk_authenticated = int(ltk_sec.get("Authenticated", 0))
        keys.ltk_enc_size = int(ltk_sec.get("EncSize", 16))
        keys.ltk_ediv = int(ltk_sec.get("EDiv", 0))
        keys.ltk_rand = int(ltk_sec.get("Rand", 0))

    if "PeripheralLongTermKey" in parser:
        pltk = parser["PeripheralLongTermKey"]
        keys.peripheral_ltk = pltk.get("Key", "")
        keys.peripheral_ltk_authenticated = int(pltk.get("Authenticated", 0))
        keys.peripheral_ltk_enc_size = int(pltk.get("EncSize", 16))
        keys.peripheral_ltk_ediv = int(pltk.get("EDiv", 0))
        keys.peripheral_ltk_rand = int(pltk.get("Rand", 0))

    if "IdentityResolvingKey" in parser:
        keys.irk = parser["IdentityResolvingKey"].get("Key", "")

    if "LocalSignatureKey" in parser:
        lsk = parser["LocalSignatureKey"]
        keys.csrk_local = lsk.get("Key", "")
        keys.csrk_local_counter = int(lsk.get("Counter", 0))

    if "RemoteSignatureKey" in parser:
        rsk = parser["RemoteSignatureKey"]
        keys.csrk_remote = rsk.get("Key", "")
        keys.csrk_remote_counter = int(rsk.get("Counter", 0))

    return keys


def discover_ble_devices(bluez_base: Path = BLUEZ_BASE) -> list[BLEKeys]:
    """Walk the BlueZ key store and return BLEKeys for every BLE-capable device."""
    devices: list[BLEKeys] = []

    if not bluez_base.exists():
        raise FileNotFoundError(f"BlueZ directory not found: {bluez_base}")

    for adapter_dir in bluez_base.iterdir():
        if not adapter_dir.is_dir():
            continue
        adapter_mac = adapter_dir.name
        if len(adapter_mac.replace(":", "")) != 12:
            continue  # skip non-MAC dirs like 'mesh'

        for device_dir in adapter_dir.iterdir():
            if not device_dir.is_dir():
                continue
            device_mac = device_dir.name
            if len(device_mac.replace(":", "")) != 12:
                continue

            info_file = device_dir / "info"
            if not info_file.exists():
                continue

            keys = read_ble_keys(info_file, adapter_mac, device_mac)
            if keys is not None:
                devices.append(keys)

    return devices
