"""Serial loopback measurement shared by the CLI and the pytest suite.

A loopback is TX tied to RX on the same port, so whatever is written comes
straight back. Any difference is a fault in the adapter, driver, or wiring.
"""

import os
import time
import traceback
from dataclasses import dataclass

import serial

BAUDS = [
    115200, 230400, 460800,
    500000, 576000, 921600, 1000000, 1500000, 2000000,
    3000000, 4000000, 6000000, 8000000, 12000000,
]


@dataclass
class Result:
    """Outcome of exercising one baud rate."""

    baud: int
    ok: bool
    throughput: float = 0.0  # bytes/sec
    detail: str = ""

    @property
    def line_rate(self) -> float:
        """Theoretical maximum bytes/sec at 8N1 (8 data + start + stop)."""
        return self.baud / 10

    @property
    def efficiency(self) -> float:
        return self.throughput / self.line_rate if self.line_rate else 0.0


def describe_mismatch(sent: bytes, got: bytes) -> str:
    """Human-readable description of the first difference."""
    if len(got) != len(sent):
        lines = [f"length differs: sent {len(sent)} B, got {len(got)} B"]
    else:
        lines = [f"same length ({len(sent)} B) but content differs"]

    n = min(len(sent), len(got))
    first_bad = next((i for i in range(n) if sent[i] != got[i]), None)
    if first_bad is None:
        if len(got) < len(sent):
            lines.append(f"prefix matched; stream truncated at offset {n}")
        else:
            lines.append(f"prefix matched; {len(got) - len(sent)} extra byte(s) received")
    else:
        lo = max(0, first_bad - 4)
        hi = min(n, first_bad + 5)
        bad = sum(1 for i in range(n) if sent[i] != got[i])
        lines += [
            f"first bad byte at offset {first_bad}",
            f"  sent[{lo}:{hi}] = {sent[lo:hi].hex(' ')}",
            f"  got [{lo}:{hi}] = {got[lo:hi].hex(' ')}",
            f"  sent=0x{sent[first_bad]:02x} ({sent[first_bad]:08b}) "
            f"got=0x{got[first_bad]:02x} ({got[first_bad]:08b})",
            f"  {bad}/{n} bytes differ ({bad / n:.1%})",
        ]
    return "\n".join("    " + line for line in lines)


def check_baud(port: str, baud: int, payload: bytes, trials: int = 3) -> Result:
    """Write `payload` and read it back `trials` times at `baud`."""
    # Allow 4x the theoretical transfer time, minimum 1 s.
    timeout = max(1.0, len(payload) * 10 / baud * 4)
    try:
        ser = serial.Serial(port, baud, timeout=timeout, write_timeout=timeout)
    except (serial.SerialException, ValueError, OSError):
        return Result(baud, False, detail="    open failed:\n" + traceback.format_exc())

    try:
        note = ""
        if ser.baudrate != baud:
            note = f"    NOTE: driver coerced baudrate to {ser.baudrate}\n"

        time.sleep(0.05)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        total = 0
        start = time.perf_counter()
        for trial in range(trials):
            written = ser.write(payload)
            ser.flush()
            if written != len(payload):
                return Result(baud, False, detail=(
                    note + f"    trial {trial}: wrote only {written}/{len(payload)} B"
                ))

            got = ser.read(len(payload))
            if got != payload:
                # Drain anything still arriving so extra bytes are visible.
                time.sleep(0.05)
                got += ser.read(ser.in_waiting)
                return Result(baud, False, detail=(
                    note + f"    trial {trial}: data mismatch\n"
                    + describe_mismatch(payload, got)
                ))
            total += len(payload)
        elapsed = time.perf_counter() - start
        return Result(baud, True, total / elapsed if elapsed > 0 else 0.0, note)
    except (serial.SerialException, OSError):
        return Result(baud, False, detail=(
            "    exception during transfer:\n" + traceback.format_exc()
        ))
    finally:
        ser.close()


def make_payload(size: int) -> bytes:
    """Random data, so a stuck or repeating line cannot pass by accident."""
    return os.urandom(size)
