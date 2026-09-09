"""Serial loopback measurement shared by the CLI and the pytest suite.

A loopback is TX tied to RX on the same port, so whatever is written comes
straight back. Any difference is a fault in the adapter, driver, or wiring.
"""

import os
import statistics
import time
import traceback
from dataclasses import dataclass, field

import serial

BAUDS = [
    115200, 230400, 460800,
    500000, 576000, 921600, 1000000, 1500000, 2000000,
    3000000, 4000000, 6000000, 8000000, 12000000,
]

# Frame sizes that matter for request/response protocols, where the cost is
# per-transaction latency rather than throughput.
FRAME_SIZES = [1, 2, 4, 8, 16, 32, 64]


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


@dataclass
class Latency:
    """Round-trip times for one frame size, in milliseconds."""

    baud: int
    size: int
    samples: list[float] = field(default_factory=list)
    detail: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.samples)

    @property
    def wire_ms(self) -> float:
        """Time the bits themselves occupy at 8N1 - the unavoidable part."""
        return self.size * 10 / self.baud * 1000

    @property
    def best(self) -> float:
        return min(self.samples)

    @property
    def median(self) -> float:
        return statistics.median(self.samples)

    @property
    def worst(self) -> float:
        return max(self.samples)

    @property
    def jitter(self) -> float:
        return self.worst - self.best

    @property
    def overhead(self) -> float:
        """Median round trip minus wire time: the adapter's own delay.

        Wire time counts once, not twice. A loopback is full duplex, so the
        first byte is already coming back while the last is still going out;
        the two directions overlap rather than add.
        """
        return self.median - self.wire_ms


def measure_latency(
    port: str,
    baud: int,
    size: int,
    iterations: int = 50,
    warmup: int = 5,
) -> Latency:
    """Time write->read round trips for a small frame.

    This is what request/response protocols actually feel. USB adapters buffer
    aggressively, so a device can have excellent throughput and still be
    unusable interactively: FTDI parts ship with a 16 ms latency timer, which
    caps them near 60 transactions/sec regardless of baud rate.
    """
    result = Latency(baud, size)
    payload = make_payload(size)
    # Generous per-frame timeout; a stalled read should fail, not hang.
    timeout = max(0.5, size * 10 / baud * 50)

    try:
        ser = serial.Serial(port, baud, timeout=timeout, write_timeout=timeout)
    except (serial.SerialException, ValueError, OSError):
        result.detail = "    open failed:\n" + traceback.format_exc()
        return result

    try:
        time.sleep(0.05)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        for i in range(warmup + iterations):
            start = time.perf_counter()
            ser.write(payload)
            ser.flush()
            got = ser.read(size)
            elapsed = (time.perf_counter() - start) * 1000

            if got != payload:
                result.samples.clear()
                result.detail = (
                    f"    iteration {i}: data mismatch\n"
                    + describe_mismatch(payload, got)
                )
                return result

            # Discard warmup: the first frames pay for buffer allocation and
            # USB pipe setup, which is not representative.
            if i >= warmup:
                result.samples.append(elapsed)

        return result
    except (serial.SerialException, OSError):
        result.samples.clear()
        result.detail = "    exception during transfer:\n" + traceback.format_exc()
        return result
    finally:
        ser.close()
