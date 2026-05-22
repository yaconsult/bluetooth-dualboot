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

    @property
    def auth_req(self) -> int:
        """Derive Windows AuthReq flags from pairing properties.

        AuthReq is a bitmask (BT spec Vol 3 Part H Section 3.5.1):
          Bits 0-1: Bonding flags (01 = bonding)
          Bit  2:   MITM protection (set if ltk_authenticated=1)
          Bit  3:   Secure Connections (assumed supported on modern devices)
          Bit  4:   Keypress notification (not used)
          Bit  5:   CT2 (Cross-Transport Key Derivation, assumed supported)
        """
        bonding = 0b01  # always bonding
        mitm = (1 << 2) if self.ltk_authenticated else 0
        secure_connections = 1 << 3
        ct2 = 1 << 5
        return bonding | mitm | secure_connections | ct2


@dataclass
class ClassicKeys:
    """BR/EDR (Classic Bluetooth) pairing keys for a single device as stored by BlueZ."""

    device_mac: str
    adapter_mac: str
    device_name: str

    link_key: str = ""
    link_key_type: int = 4
    pin_length: int = 0


# Union type for any paired device
AnyDeviceKeys = BLEKeys | ClassicKeys


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


def read_classic_keys(info_path: Path, adapter_mac: str, device_mac: str) -> ClassicKeys | None:
    """Parse a BlueZ info file and return ClassicKeys if it is a BR/EDR device, else None."""
    parser = _read_info_file(info_path)

    general = parser["General"] if "General" in parser else {}
    technologies = general.get("SupportedTechnologies", "")

    if "BR/EDR" not in technologies:
        return None

    keys = ClassicKeys(
        device_mac=device_mac,
        adapter_mac=adapter_mac,
        device_name=general.get("Name", "Unknown"),
    )

    if "LinkKey" in parser:
        lk = parser["LinkKey"]
        keys.link_key = lk.get("Key", "")
        keys.link_key_type = int(lk.get("Type", 4))
        keys.pin_length = int(lk.get("PINLength", 0))

    return keys


def patch_ble_info_file(
    info_path: Path,
    ltk: str,
    ltk_rand: int,
    ltk_ediv: int,
    irk: str,
    peripheral_ltk: str = "",
    peripheral_ltk_rand: int = 0,
    peripheral_ltk_ediv: int = 0,
    csrk_local: str = "",
    csrk_remote: str = "",
) -> None:
    """Overwrite BLE key sections in an existing BlueZ info file.

    Used for Windows→Linux BLE sync: the Windows keys (hex-encoded, same byte
    order) are written into the Linux info file so that both OSes share the
    same keys (with the Windows pairing as the canonical source).

    Preserves [General], [DeviceID], [ConnectionParameters] and any other
    non-key sections unchanged.
    """
    parser = _read_info_file(info_path)

    # Update LongTermKey section
    if "LongTermKey" not in parser:
        parser.add_section("LongTermKey")
    parser.set("LongTermKey", "Key", ltk)
    parser.set("LongTermKey", "Authenticated", "0")
    parser.set("LongTermKey", "EncSize", "16")
    parser.set("LongTermKey", "EDiv", str(ltk_ediv))
    parser.set("LongTermKey", "Rand", str(ltk_rand))

    # Update PeripheralLongTermKey and SlaveLongTermKey if we have peripheral keys
    if peripheral_ltk:
        for section in ("PeripheralLongTermKey", "SlaveLongTermKey"):
            if section not in parser:
                parser.add_section(section)
            parser.set(section, "Key", peripheral_ltk)
            parser.set(section, "Authenticated", "0")
            parser.set(section, "EncSize", "16")
            parser.set(section, "EDiv", str(peripheral_ltk_ediv))
            parser.set(section, "Rand", str(peripheral_ltk_rand))

    # Update IRK
    if irk:
        if "IdentityResolvingKey" not in parser:
            parser.add_section("IdentityResolvingKey")
        parser.set("IdentityResolvingKey", "Key", irk)

    # Update CSRK sections
    if csrk_local:
        if "LocalSignatureKey" not in parser:
            parser.add_section("LocalSignatureKey")
        parser.set("LocalSignatureKey", "Key", csrk_local)
        parser.set("LocalSignatureKey", "Counter", "0")
        parser.set("LocalSignatureKey", "Authenticated", "false")

    if csrk_remote:
        if "RemoteSignatureKey" not in parser:
            parser.add_section("RemoteSignatureKey")
        parser.set("RemoteSignatureKey", "Key", csrk_remote)
        parser.set("RemoteSignatureKey", "Counter", "0")
        parser.set("RemoteSignatureKey", "Authenticated", "false")

    # Write back — configparser lowercases keys by default, so we do it manually
    _write_info_file(info_path, parser)


def _write_info_file(info_path: Path, parser: configparser.ConfigParser) -> None:
    """Write a BlueZ info file preserving the exact key casing BlueZ expects.

    configparser lowercases option names by default, so we write manually
    to preserve correct casing (e.g. 'Key', 'EDiv', 'EncSize').
    """
    lines: list[str] = []
    for section in parser.sections():
        lines.append(f"[{section}]")
        for key, value in parser.items(section):
            # Restore BlueZ-expected casing for known keys
            cased_key = _BLUEZ_KEY_CASING.get(key, key)
            lines.append(f"{cased_key}={value}")
        lines.append("")
    info_path.write_text("\n".join(lines))


# BlueZ expects specific casing for info file keys
_BLUEZ_KEY_CASING: dict[str, str] = {
    "name": "Name",
    "appearance": "Appearance",
    "addresstype": "AddressType",
    "supportedtechnologies": "SupportedTechnologies",
    "trusted": "Trusted",
    "blocked": "Blocked",
    "cablepairing": "CablePairing",
    "wakeallowed": "WakeAllowed",
    "services": "Services",
    "key": "Key",
    "authenticated": "Authenticated",
    "encsize": "EncSize",
    "ediv": "EDiv",
    "rand": "Rand",
    "counter": "Counter",
    "type": "Type",
    "pinlength": "PINLength",
    "source": "Source",
    "vendor": "Vendor",
    "product": "Product",
    "version": "Version",
    "mininterval": "MinInterval",
    "maxinterval": "MaxInterval",
    "latency": "Latency",
    "timeout": "Timeout",
    "class": "Class",
}


def _is_mac_dir(name: str) -> bool:
    """Return True if a directory name looks like a Bluetooth MAC address."""
    return len(name.replace(":", "").replace("-", "")) == 12


def discover_ble_devices(bluez_base: Path = BLUEZ_BASE) -> list[BLEKeys]:
    """Walk the BlueZ key store and return BLEKeys for every BLE-capable device."""
    return [d for d in discover_all_devices(bluez_base) if isinstance(d, BLEKeys)]


def discover_all_devices(bluez_base: Path = BLUEZ_BASE) -> list[AnyDeviceKeys]:
    """Walk the BlueZ key store and return keys for ALL paired devices (BLE and Classic)."""
    devices: list[AnyDeviceKeys] = []

    if not bluez_base.exists():
        raise FileNotFoundError(f"BlueZ directory not found: {bluez_base}")

    for adapter_dir in sorted(bluez_base.iterdir()):
        if not adapter_dir.is_dir() or not _is_mac_dir(adapter_dir.name):
            continue
        adapter_mac = adapter_dir.name

        for device_dir in sorted(adapter_dir.iterdir()):
            if not device_dir.is_dir() or not _is_mac_dir(device_dir.name):
                continue
            device_mac = device_dir.name

            info_file = device_dir / "info"
            if not info_file.exists():
                continue

            # Try BLE first, then Classic
            keys: AnyDeviceKeys | None = read_ble_keys(info_file, adapter_mac, device_mac)
            if keys is None:
                keys = read_classic_keys(info_file, adapter_mac, device_mac)
            if keys is not None:
                devices.append(keys)

    return devices
