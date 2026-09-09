"""Port selection: `.env` file, environment, and USB auto-detection.

Precedence, highest first:

    1. an explicit --port argument
    2. the PICOUART_PORT environment variable
    3. PICOUART_PORT in a .env file next to this module
    4. auto-detection by USB VID:PID

Port names like COM11 are not stable - they depend on enumeration order and
change when devices are replugged - so pinning one in .env or matching on
VID:PID is more reliable than remembering the number.
"""

import os
from pathlib import Path

from serial.tools import list_ports

ENV_FILE = Path(__file__).with_name(".env")
ENV_VAR = "PICOUART_PORT"

# USB VID:PID of devices we can identify. The Pico's CDC interfaces both
# report the same ID, so a board exposes two ports (UART0 and UART1).
KNOWN_DEVICES = {
    (0x2E8A, 0x000A): "Raspberry Pi Pico (pico-uart-bridge)",
    (0x2E8A, 0x0005): "Raspberry Pi Pico (stdio USB)",
    (0x0403, 0x6001): "FTDI FT232",
    (0x0403, 0x6015): "FTDI FT231X",
    (0x10C4, 0xEA60): "Silicon Labs CP210x",
    (0x1A86, 0x7523): "WCH CH340",
}

PICO_IDS = {(0x2E8A, 0x000A), (0x2E8A, 0x0005)}


def load_dotenv(path: Path = ENV_FILE) -> dict[str, str]:
    """Parse a minimal KEY=VALUE .env file. Missing file is not an error."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            values[key.strip()] = value
    return values


def describe(p) -> str:
    name = KNOWN_DEVICES.get((p.vid, p.pid))
    if name:
        return f"{p.device}  {name}"
    if p.vid is not None:
        return f"{p.device}  {p.description} [{p.vid:04X}:{p.pid:04X}]"
    return f"{p.device}  {p.description}"


def list_candidates() -> list[str]:
    """Human-readable list of attached serial ports, for error messages."""
    ports = sorted(list_ports.comports(), key=lambda p: p.device)
    if not ports:
        return ["  (no serial ports found)"]
    return ["  " + describe(p) for p in ports]


def autodetect() -> str:
    """Return the port of the single attached Pico bridge.

    Raises if there is no Pico, or if the choice is ambiguous. A board exposes
    two ports (UART0 and UART1), so the first is picked only when exactly one
    board is present.
    """
    picos = sorted(
        (p for p in list_ports.comports() if (p.vid, p.pid) in PICO_IDS),
        key=lambda p: p.device,
    )

    if not picos:
        raise RuntimeError(
            "No Raspberry Pi Pico found. Attached ports:\n"
            + "\n".join(list_candidates())
            + f"\n\nSet a port explicitly with --port, {ENV_VAR}=..., or a .env file."
        )

    serials = {p.serial_number for p in picos}
    if len(serials) > 1:
        raise RuntimeError(
            "Multiple Pico boards attached; pick one explicitly:\n"
            + "\n".join("  " + describe(p) for p in picos)
        )

    # One board, two interfaces: UART0 enumerates first.
    return picos[0].device


def resolve_port(explicit: str | None = None) -> str:
    """Apply the precedence order and return a port name."""
    if explicit and explicit != "auto":
        return explicit

    if not explicit:
        from_env = os.environ.get(ENV_VAR) or load_dotenv().get(ENV_VAR)
        if from_env:
            return from_env

    return autodetect()
