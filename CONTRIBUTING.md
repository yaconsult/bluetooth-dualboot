# Contributing

## Development Setup

```bash
git clone https://github.com/yaconsult/bluetooth-dualboot.git
cd bluetooth-dualboot
uv sync --group dev
```

## Running Tests

```bash
uv run pytest -v
```

## Code Style

This project uses `black` (formatting) and `ruff` (linting).

```bash
uv run black bluetooth_dualboot/ tests/
uv run ruff check bluetooth_dualboot/ tests/
```

Both are enforced before committing. Run them before opening a PR.

## Project Structure

```
bluetooth_dualboot/
    linux_bt.py    — Read BLE + Classic pairing keys from BlueZ (/var/lib/bluetooth)
    windows_bt.py  — Read/write Windows SYSTEM registry hive (patch + create via reged)
    utils.py       — MAC normalization, byte-reversal, NTFS mount detection
    sync.py        — CLI entry point and orchestration
tests/
    test_linux_bt.py
    test_utils.py
```

## Adding Support for a New Device Type

1. Add a new `Keys` dataclass in `linux_bt.py`
2. Add a `read_*_keys()` function and include it in `discover_all_devices()`
3. Add corresponding read/write functions in `windows_bt.py`
4. Add a `_sync_*()` function in `sync.py` and call it from `main()`
5. Add tests

## Reporting Issues

Please include:
- Your Linux distro and BlueZ version (`bluetoothctl --version`)
- The device type (BLE or Classic, manufacturer/model if known)
- Output of `sudo uv run bt-sync --dry-run --verbose`
- **Do not include actual key values** from your system in bug reports
