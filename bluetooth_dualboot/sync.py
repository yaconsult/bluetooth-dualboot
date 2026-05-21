"""CLI entry point: sync all Linux Bluetooth pairing keys into the Windows registry hive."""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
import sys
from pathlib import Path

from bluetooth_dualboot.linux_bt import AnyDeviceKeys, BLEKeys, ClassicKeys, discover_all_devices
from bluetooth_dualboot.utils import (
    find_ntfs_mounts,
    find_windows_system_hive,
    mac_to_windows_key,
    reverse_hex_key,
)
from bluetooth_dualboot.windows_bt import (
    WindowsBLEEntry,
    WindowsClassicEntry,
    create_ble_entry,
    create_classic_entry,
    patch_ble_entry,
    patch_classic_entry,
    read_windows_ble_entries,
    read_windows_classic_entries,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bt-sync",
        description=(
            "Sync all Linux Bluetooth pairing keys (BLE and Classic) into the Windows "
            "registry so every paired device works in both OSes without re-pairing."
        ),
    )
    parser.add_argument(
        "--windows-mount",
        metavar="PATH",
        help="Mount point of the Windows NTFS partition (auto-detected if omitted)",
    )
    parser.add_argument(
        "--bluez-dir",
        metavar="PATH",
        default="/var/lib/bluetooth",
        help="Path to the BlueZ key store (default: /var/lib/bluetooth)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without writing anything",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed key information",
    )
    return parser


def _find_hive(windows_mount: str | None, verbose: bool) -> Path:
    """Locate the Windows SYSTEM hive, auto-detecting the mount if needed."""
    if windows_mount:
        mounts = [Path(windows_mount)]
    else:
        mounts = find_ntfs_mounts()
        if not mounts:
            print("ERROR: No NTFS partitions found. Is the Windows drive mounted?", file=sys.stderr)
            sys.exit(1)

    for mount in mounts:
        hive = find_windows_system_hive(mount)
        if hive:
            if verbose:
                print(f"  Found Windows SYSTEM hive: {hive}")
            return hive

    print(
        "ERROR: Could not find Windows\\System32\\config\\SYSTEM on any NTFS mount.",
        file=sys.stderr,
    )
    print(f"  Searched: {[str(m) for m in mounts]}", file=sys.stderr)
    sys.exit(1)


def _mac_candidates(mac: str) -> tuple[str, str]:
    """Return (normal, reversed) lowercase no-sep MAC strings for matching."""
    normal = mac_to_windows_key(mac)
    reversed_ = bytes(reversed(bytes.fromhex(normal))).hex()
    return normal, reversed_


def _find_ble_win_entry(lk: BLEKeys, win_ble: list[WindowsBLEEntry]) -> WindowsBLEEntry | None:
    normal, reversed_ = _mac_candidates(lk.device_mac)
    for we in win_ble:
        if we.device_key in (normal, reversed_):
            return we
    return None


def _find_classic_win_entry(
    lk: ClassicKeys, win_classic: list[WindowsClassicEntry]
) -> WindowsClassicEntry | None:
    normal, reversed_ = _mac_candidates(lk.device_mac)
    for we in win_classic:
        if we.device_key in (normal, reversed_):
            return we
    return None


def _adapter_win_key(adapter_mac: str, win_ble: list[WindowsBLEEntry]) -> str:
    """Derive the Windows adapter key from existing entries or by normalising the MAC."""
    for we in win_ble:
        return we.adapter_key
    return mac_to_windows_key(adapter_mac)


def _mac_to_address_int(mac: str) -> int:
    """Convert a MAC string to the 64-bit little-endian integer Windows stores as Address."""
    b = bytes.fromhex(mac_to_windows_key(mac))
    return int.from_bytes(bytes(reversed(b)), "little")


def _sync_ble(
    lk: BLEKeys,
    we: WindowsBLEEntry | None,
    adapter_win_key: str,
    hive_path: Path,
    dry_run: bool,
    verbose: bool,
) -> bool:
    """Sync a BLE device — patch if entry exists, create if not. Returns True if changed."""
    new_ltk = reverse_hex_key(lk.ltk) if lk.ltk else None
    new_irk = reverse_hex_key(lk.irk) if lk.irk else None
    new_csrk_inbound = reverse_hex_key(lk.csrk_local) if lk.csrk_local else None
    new_csrk_outbound = reverse_hex_key(lk.csrk_remote) if lk.csrk_remote else None

    if we is None:
        # No existing Windows entry — create from scratch
        device_win_key = mac_to_windows_key(lk.device_mac)
        address = _mac_to_address_int(lk.device_mac)
        address_type = 0 if lk.address_type == "public" else 1

        if verbose or dry_run:
            print("    Action: CREATE new Windows BLE entry")
            if new_ltk:
                print(f"    LTK:  {new_ltk.hex().upper()}")
            if new_irk:
                print(f"    IRK:  {new_irk.hex().upper()}")

        if dry_run:
            print(f"  [{lk.device_name}] DRY RUN — would create new Windows BLE entry.")
            return True

        create_ble_entry(
            hive_path=hive_path,
            adapter_key=adapter_win_key,
            device_key=device_win_key,
            ltk=new_ltk or b"\x00" * 16,
            irk=new_irk or b"\x00" * 16,
            key_length=lk.ltk_enc_size,
            erand=lk.ltk_rand,
            ediv=lk.ltk_ediv,
            address=address,
            address_type=address_type,
            auth_req=lk.auth_req,
            csrk_inbound=new_csrk_inbound,
            csrk_outbound=new_csrk_outbound,
        )
        print(f"  [{lk.device_name}] Created new Windows BLE entry.")
        return True

    # Entry exists — check if update is needed
    needs_update = (
        (new_ltk and new_ltk != we.ltk)
        or (new_irk and new_irk != we.irk)
        or (new_csrk_inbound and we.csrk_inbound and new_csrk_inbound != we.csrk_inbound)
        or (new_csrk_outbound and we.csrk_outbound and new_csrk_outbound != we.csrk_outbound)
    )

    if not needs_update:
        print(f"  [{lk.device_name}] BLE keys already in sync — nothing to do.")
        return False

    if verbose or dry_run:
        print("    Action: PATCH existing Windows BLE entry")
        if new_ltk and new_ltk != we.ltk:
            print(f"    LTK:  {we.ltk.hex().upper()} → {new_ltk.hex().upper()}")
        if new_irk and new_irk != we.irk:
            print(f"    IRK:  {we.irk.hex().upper()} → {new_irk.hex().upper()}")
        if new_csrk_inbound and we.csrk_inbound and new_csrk_inbound != we.csrk_inbound:
            print(
                f"    CSRK(inbound):  {we.csrk_inbound.hex().upper()} → "
                f"{new_csrk_inbound.hex().upper()}"
            )
        if new_csrk_outbound and we.csrk_outbound and new_csrk_outbound != we.csrk_outbound:
            print(
                f"    CSRK(outbound): {we.csrk_outbound.hex().upper()} → "
                f"{new_csrk_outbound.hex().upper()}"
            )

    if dry_run:
        print(f"  [{lk.device_name}] DRY RUN — would patch existing Windows BLE entry.")
        return True

    patch_ble_entry(
        hive_path=hive_path,
        adapter_key=we.adapter_key,
        device_key=we.device_key,
        ltk=new_ltk if new_ltk else we.ltk,
        irk=new_irk if new_irk else we.irk,
        csrk_inbound=new_csrk_inbound,
        csrk_outbound=new_csrk_outbound,
    )
    print(f"  [{lk.device_name}] BLE keys patched in Windows registry.")
    return True


def _sync_classic(
    lk: ClassicKeys,
    we: WindowsClassicEntry | None,
    adapter_win_key: str,
    hive_path: Path,
    dry_run: bool,
    verbose: bool,
) -> bool:
    """Sync a Classic BT device — patch if entry exists, create if not. Returns True if changed."""
    if not lk.link_key:
        print(f"  [{lk.device_name}] No LinkKey found in Linux — skipping.")
        return False

    # Classic link keys are stored as-is (no byte-reversal needed for BR/EDR)
    new_link_key = bytes.fromhex(lk.link_key)
    device_win_key = mac_to_windows_key(lk.device_mac)

    if we is None:
        if verbose or dry_run:
            print("    Action: CREATE new Windows Classic BT entry")
            print(f"    LinkKey: {new_link_key.hex().upper()}")

        if dry_run:
            print(f"  [{lk.device_name}] DRY RUN — would create new Windows Classic entry.")
            return True

        create_classic_entry(
            hive_path=hive_path,
            adapter_key=adapter_win_key,
            device_key=device_win_key,
            link_key=new_link_key,
        )
        print(f"  [{lk.device_name}] Created new Windows Classic BT entry.")
        return True

    if we.link_key == new_link_key:
        print(f"  [{lk.device_name}] Classic key already in sync — nothing to do.")
        return False

    if verbose or dry_run:
        print("    Action: PATCH existing Windows Classic entry")
        print(f"    LinkKey: {we.link_key.hex().upper()} → {new_link_key.hex().upper()}")

    if dry_run:
        print(f"  [{lk.device_name}] DRY RUN — would patch existing Windows Classic entry.")
        return True

    patch_classic_entry(
        hive_path=hive_path,
        adapter_key=we.adapter_key,
        device_key=we.device_key,
        link_key=new_link_key,
    )
    print(f"  [{lk.device_name}] Classic key patched in Windows registry.")
    return True


def _backup_hive(hive_path: Path) -> Path:
    """Create a timestamped backup of the Windows SYSTEM hive before any writes.

    The backup is written alongside the original hive file. If anything goes
    wrong the user can restore it by copying it back over the SYSTEM file.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = hive_path.with_name(f"SYSTEM.bt-sync-backup-{timestamp}")
    shutil.copy2(hive_path, backup_path)
    return backup_path


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("ERROR: This script must be run as root (sudo).", file=sys.stderr)
        sys.exit(1)

    print("=== bt-sync: Bluetooth Dual-Boot Key Sync ===\n")

    # 1. Discover all Linux paired devices
    print(f"[1/4] Reading Linux BT keys from {args.bluez_dir} ...")
    try:
        linux_devices: list[AnyDeviceKeys] = discover_all_devices(Path(args.bluez_dir))
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if not linux_devices:
        print("  No paired devices found in Linux BT store.")
        sys.exit(0)

    ble_devices = [d for d in linux_devices if isinstance(d, BLEKeys)]
    classic_devices = [d for d in linux_devices if isinstance(d, ClassicKeys)]
    print(f"  Found {len(ble_devices)} BLE + {len(classic_devices)} Classic device(s):")
    for d in linux_devices:
        dtype = "BLE" if isinstance(d, BLEKeys) else "Classic"
        print(f"    - [{dtype}] {d.device_name} ({d.device_mac})")

    # 2. Locate Windows SYSTEM hive
    print("\n[2/4] Locating Windows SYSTEM hive ...")
    hive_path = _find_hive(args.windows_mount, args.verbose)
    print(f"  Hive: {hive_path}")

    # 3. Read Windows BT entries
    print("\n[3/4] Reading Windows BT registry entries ...")
    win_ble = read_windows_ble_entries(hive_path)
    win_classic = read_windows_classic_entries(hive_path)
    print(f"  Found {len(win_ble)} BLE + {len(win_classic)} Classic entry(ies) in Windows.")

    # Determine Windows adapter key (needed for create operations)
    adapter_win_key = (
        _adapter_win_key(linux_devices[0].adapter_mac, win_ble) if linux_devices else ""
    )

    # 4. Backup hive, then sync all devices
    print("\n[4/4] Syncing keys ...")
    if not args.dry_run:
        backup_path = _backup_hive(hive_path)
        print(f"  Backup: {backup_path}")
    changed = 0

    for lk in ble_devices:
        print(f"\n  [BLE] {lk.device_name} ({lk.device_mac})")
        we = _find_ble_win_entry(lk, win_ble)
        if args.verbose:
            status = "found in Windows" if we else "NOT in Windows — will create"
            print(f"    Windows entry: {status}")
        if _sync_ble(lk, we, adapter_win_key, hive_path, args.dry_run, args.verbose):
            changed += 1

    for lk in classic_devices:
        print(f"\n  [Classic] {lk.device_name} ({lk.device_mac})")
        we = _find_classic_win_entry(lk, win_classic)
        if args.verbose:
            status = "found in Windows" if we else "NOT in Windows — will create"
            print(f"    Windows entry: {status}")
        if _sync_classic(lk, we, adapter_win_key, hive_path, args.dry_run, args.verbose):
            changed += 1

    print()
    if args.dry_run:
        print(f"DRY RUN complete. {changed} device(s) would be updated.")
    else:
        print(f"Done. {changed} device(s) updated.")
        if changed:
            print("Boot into Windows — your Bluetooth devices should connect automatically.")


if __name__ == "__main__":
    main()
