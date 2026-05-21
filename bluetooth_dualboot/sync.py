"""CLI entry point: sync Linux BLE Bluetooth keys into the Windows registry hive."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from bluetooth_dualboot.linux_bt import BLEKeys, discover_ble_devices
from bluetooth_dualboot.utils import (
    find_ntfs_mounts,
    find_windows_system_hive,
    mac_to_windows_key,
    reverse_hex_key,
)
from bluetooth_dualboot.windows_bt import read_windows_bt_entries, write_ble_keys_to_hive


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bt-sync",
        description=(
            "Sync Linux Bluetooth BLE pairing keys into the Windows registry so the same "
            "mouse works in both OSes without re-pairing."
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


def _match_devices(
    linux_devices: list[BLEKeys],
    windows_entries: list,
    verbose: bool,
) -> list[tuple]:
    """Match Linux BLE devices to Windows registry entries by MAC address.

    Returns list of (linux_keys, windows_entry) pairs.
    Windows and Linux may store the MAC byte-reversed, so we normalise both sides.
    """
    matched = []

    for lk in linux_devices:
        # Linux MAC e.g. 'E4:9F:64:0B:E8:1C' → windows key 'e49f640be81c'
        linux_win_key = mac_to_windows_key(lk.device_mac)
        # Also try byte-reversed MAC (some adapters store it reversed)
        linux_mac_bytes = bytes.fromhex(linux_win_key)
        linux_win_key_reversed = bytes(reversed(linux_mac_bytes)).hex()

        for we in windows_entries:
            if we.device_key in (linux_win_key, linux_win_key_reversed):
                if verbose:
                    print(
                        f"  Matched: Linux {lk.device_mac!r} ({lk.device_name!r}) "
                        f"→ Windows {we.adapter_key}\\{we.device_key}"
                    )
                matched.append((lk, we))
                break
        else:
            if verbose:
                print(
                    f"  No Windows entry found for Linux device {lk.device_mac!r} "
                    f"({lk.device_name!r}) — skipping"
                )

    return matched


def _sync_pair(
    lk: BLEKeys,
    we,
    hive_path: Path,
    dry_run: bool,
    verbose: bool,
) -> bool:
    """Compute Windows-format keys from Linux keys and write them to the hive.

    Returns True if changes were (or would be) made.
    """
    new_ltk = reverse_hex_key(lk.ltk) if lk.ltk else None
    new_irk = reverse_hex_key(lk.irk) if lk.irk else None
    new_csrk_local = reverse_hex_key(lk.csrk_local) if lk.csrk_local else None
    new_csrk_remote = reverse_hex_key(lk.csrk_remote) if lk.csrk_remote else None

    needs_update = (
        (new_ltk and new_ltk != we.ltk)
        or (new_irk and new_irk != we.irk)
        or (new_csrk_local and we.csrk_inbound and new_csrk_local != we.csrk_inbound)
        or (new_csrk_remote and we.csrk_outbound and new_csrk_remote != we.csrk_outbound)
    )

    if not needs_update:
        print(f"  [{lk.device_name}] Keys already in sync — nothing to do.")
        return False

    if verbose or dry_run:
        if new_ltk and new_ltk != we.ltk:
            print(f"    LTK:  {we.ltk.hex().upper()} → {new_ltk.hex().upper()}")
        if new_irk and new_irk != we.irk:
            print(f"    IRK:  {we.irk.hex().upper()} → {new_irk.hex().upper()}")
        if new_csrk_local and we.csrk_inbound and new_csrk_local != we.csrk_inbound:
            old = we.csrk_inbound.hex().upper()
            new = new_csrk_local.hex().upper()
            print(f"    CSRK(inbound):  {old} → {new}")
        if new_csrk_remote and we.csrk_outbound and new_csrk_remote != we.csrk_outbound:
            old = we.csrk_outbound.hex().upper()
            new = new_csrk_remote.hex().upper()
            print(f"    CSRK(outbound): {old} → {new}")

    if dry_run:
        print(f"  [{lk.device_name}] DRY RUN — no changes written.")
        return True

    write_ble_keys_to_hive(
        hive_path=hive_path,
        adapter_key=we.adapter_key,
        device_key=we.device_key,
        ltk=new_ltk if new_ltk else we.ltk,
        irk=new_irk if new_irk else we.irk,
        csrk_inbound=new_csrk_local,
        csrk_outbound=new_csrk_remote,
    )
    print(f"  [{lk.device_name}] Keys written to Windows registry hive.")
    return True


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("ERROR: This script must be run as root (sudo).", file=sys.stderr)
        sys.exit(1)

    print("=== bt-sync: Bluetooth Dual-Boot Key Sync ===\n")

    # 1. Discover Linux BLE devices
    print(f"[1/4] Reading Linux BT keys from {args.bluez_dir} ...")
    try:
        linux_devices = discover_ble_devices(Path(args.bluez_dir))
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if not linux_devices:
        print("  No BLE devices found in Linux BT store. Is any BLE device paired?")
        sys.exit(0)

    print(f"  Found {len(linux_devices)} BLE device(s):")
    for d in linux_devices:
        print(f"    - {d.device_name} ({d.device_mac})")

    # 2. Locate Windows SYSTEM hive
    print("\n[2/4] Locating Windows SYSTEM hive ...")
    hive_path = _find_hive(args.windows_mount, args.verbose)
    print(f"  Hive: {hive_path}")

    # 3. Read Windows BT entries
    print("\n[3/4] Reading Windows BT registry entries ...")
    windows_entries = read_windows_bt_entries(hive_path)
    if not windows_entries:
        print("  No BLE entries found in Windows registry.")
        print("  Have you ever paired this device in Windows? If not, pair it once first.")
        sys.exit(0)

    print(f"  Found {len(windows_entries)} BLE entry(ies) in Windows registry.")

    # 4. Match and sync
    print("\n[4/4] Matching and syncing keys ...")
    matched = _match_devices(linux_devices, windows_entries, args.verbose)

    if not matched:
        print("\nNo matching devices found between Linux and Windows.")
        print("Ensure the device has been paired in BOTH OSes at least once.")
        sys.exit(0)

    changed = 0
    for lk, we in matched:
        print(f"\n  Device: {lk.device_name} ({lk.device_mac})")
        if _sync_pair(lk, we, hive_path, args.dry_run, args.verbose):
            changed += 1

    print()
    if args.dry_run:
        print(f"DRY RUN complete. {changed} device(s) would be updated.")
    else:
        print(f"Done. {changed} device(s) updated.")
        if changed:
            print("Boot into Windows — your Bluetooth device should connect automatically.")


if __name__ == "__main__":
    main()
