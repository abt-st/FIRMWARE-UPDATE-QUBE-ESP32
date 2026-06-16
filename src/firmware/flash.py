"""
flash.py — Build & flash QUBE firmware via HTTP /update endpoint.

Usage:
    uv run python src/firmware/flash.py                          # auto-detect IP, build + upload
    uv run python src/firmware/flash.py --ip 192.168.100.50      # explicit IP
    uv run python src/firmware/flash.py --build-only              # build without upload
    uv run python src/firmware/flash.py --upload-only             # upload last build (skip compile)

Solves the OneDrive lock issue: uses HTTP multipart upload to /update
instead of espota.py/esptool which lock the .bin file. If OneDrive holds
firmware.bin locked, the ELF is still converted to a temp .bin for upload.
"""

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

FIRMWARE_DIR = Path(__file__).parent
BUILD_DIR = FIRMWARE_DIR / ".pio" / "build" / "esp32dev"
ELF_PATH = BUILD_DIR / "firmware.elf"
BIN_PATH = BUILD_DIR / "firmware.bin"
DEFAULT_IP = "192.168.100.50"

# esptool paths from platformio
PLATFORMIO_HOME = Path.home() / ".platformio"
ESPTOOL = str(PLATFORMIO_HOME / "packages" / "tool-esptoolpy" / "esptool.py")


def find_esptool() -> str:
    """Find esptool.py in platformio packages."""
    if Path(ESPTOOL).exists():
        return ESPTOOL
    # Fallback: try pip
    try:
        subprocess.run([sys.executable, "-m", "esptool", "version"], capture_output=True, check=True)
        return f"{sys.executable} -m esptool"
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    print("ERROR: esptool.py not found. Install via: pio pkg install -t tool-esptoolpy")
    sys.exit(1)


def build() -> bool:
    """Run PlatformIO build. Returns True on success (or ELF exists even if .bin locked)."""
    print("Building firmware...")
    result = subprocess.run(
        ["pio", "run", "-e", "esp32dev"],
        cwd=FIRMWARE_DIR,
        capture_output=True,
        text=True,
        timeout=180,
    )

    # Even if pio returns non-zero, check if ELF was produced (OneDrive lock on .bin)
    if ELF_PATH.exists():
        elf_kb = ELF_PATH.stat().st_size // 1024
        print(f"Build OK (ELF: {elf_kb} KB)")

        if BIN_PATH.exists():
            bin_kb = BIN_PATH.stat().st_size // 1024
            print(f"  firmware.bin: {bin_kb} KB")
        else:
            print("  firmware.bin locked by OneDrive — will convert ELF in temp dir")
        return True

    print("BUILD FAILED:")
    for line in result.stdout.splitlines()[-5:]:
        print(f"  {line}")
    for line in result.stderr.splitlines()[-10:]:
        print(f"  {line}")
    return False


def elf_to_bin() -> Path:
    """Convert ELF to BIN. Tries original path first, falls back to temp dir."""
    # If BIN exists and is recent, use it
    if BIN_PATH.exists():
        return BIN_PATH

    # Convert ELF to temp .bin
    print("Converting ELF → BIN via esptool...")
    tmp_bin = Path(tempfile.gettempdir()) / "qube_firmware.bin"

    esptool_parts = find_esptool().split()
    cmd = esptool_parts + [
        "--chip", "esp32",
        "elf2image",
        "--flash_mode", "dout",
        "--flash_size", "4MB",
        "-o", str(tmp_bin),
        str(ELF_PATH),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"esptool failed: {result.stderr}")
        sys.exit(1)

    # esptool may add segment suffixes — find the main one
    candidates = list(tmp_bin.parent.glob(tmp_bin.name + "*"))
    if not candidates:
        print("ERROR: esptool produced no output")
        sys.exit(1)

    # Use the largest file (the merged image)
    main_bin = max(candidates, key=lambda p: p.stat().st_size)
    print(f"  Generated: {main_bin.name} ({main_bin.stat().st_size // 1024} KB)")
    return main_bin


def upload(ip: str, bin_path: Path | None = None) -> bool:
    """Upload firmware via HTTP POST to /update."""
    if bin_path is None:
        bin_path = elf_to_bin()

    if not bin_path.exists():
        print(f"ERROR: {bin_path} not found.")
        return False

    url = f"http://{ip}/update"
    size_kb = bin_path.stat().st_size // 1024
    print(f"Uploading {size_kb} KB to {url}...")

    try:
        with open(bin_path, "rb") as f:
            resp = requests.post(
                url,
                files={"file": ("firmware.bin", f, "application/octet-stream")},
                timeout=60,
            )
        data = resp.json()
        if data.get("ok"):
            print("Upload OK. ESP32 rebooting...")
            return True
        print(f"Upload failed: {data}")
        return False
    except requests.ConnectionError:
        print(f"ERROR: Cannot reach {ip}. Is the ESP32 on?")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def verify(ip: str, retries: int = 8) -> bool:
    """Wait for ESP32 to come back after reboot."""
    print("Waiting for ESP32 reboot...")
    for i in range(retries):
        time.sleep(2)
        try:
            r = requests.get(f"http://{ip}/state", timeout=3)
            state = r.json()
            print(f"ESP32 online: mode={state['mode']} v={state['v_bus']:.1f}V pos={state['position_deg']:.1f}")
            return True
        except Exception:
            print(f"  attempt {i + 1}/{retries}...")
    print("WARNING: ESP32 did not come back within timeout")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Build & flash QUBE firmware via HTTP")
    parser.add_argument("--ip", default=DEFAULT_IP, help=f"ESP32 IP (default: {DEFAULT_IP})")
    parser.add_argument("--build-only", action="store_true", help="Build without uploading")
    parser.add_argument("--upload-only", action="store_true", help="Upload last build, skip compile")
    args = parser.parse_args()

    ok = True

    if not args.upload_only:
        ok = build()

    if ok and not args.build_only:
        ok = upload(args.ip)
        if ok:
            verify(args.ip)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
