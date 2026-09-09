"""Find the max error-free baud rate on a serial loopback (TX tied to RX).

Reports exactly what goes wrong at each baud: short reads, byte-mismatch
offsets with hex context, coerced baudrates, and full exception tracebacks.

Usage:
    python loopback_speed.py --port COM11 [--bytes 4096] [--trials 3]
"""

import argparse
import os
import sys
import time
import traceback

import serial

BAUDS = [
    115200, 230400, 460800,
    500000, 576000, 921600, 1000000, 1500000, 2000000,
    3000000, 4000000, 6000000, 8000000, 12000000,
]


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


def test_baud(port: str, baud: int, payload: bytes, trials: int) -> tuple[bool, float, str]:
    """Return (ok, throughput_bytes_per_sec, detail)."""
    # Allow 4x the theoretical transfer time, minimum 1 s.
    timeout = max(1.0, len(payload) * 10 / baud * 4)
    try:
        ser = serial.Serial(port, baud, timeout=timeout, write_timeout=timeout)
    except (serial.SerialException, ValueError, OSError):
        return False, 0.0, "    open failed:\n" + traceback.format_exc()

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
                return False, 0.0, note + f"    trial {trial}: wrote only {written}/{len(payload)} B"

            got = ser.read(len(payload))
            if got != payload:
                # Drain anything still arriving so extra bytes are visible.
                time.sleep(0.05)
                got += ser.read(ser.in_waiting)
                return False, 0.0, (
                    note + f"    trial {trial}: data mismatch\n" + describe_mismatch(payload, got)
                )
            total += len(payload)
        elapsed = time.perf_counter() - start
        return True, (total / elapsed if elapsed > 0 else 0.0), note
    except (serial.SerialException, OSError):
        return False, 0.0, "    exception during transfer:\n" + traceback.format_exc()
    finally:
        ser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM11")
    parser.add_argument("--bytes", type=int, default=4096, help="payload size per trial")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument(
        "--stop-on-fail",
        action="store_true",
        help="stop at the first failing baud rate instead of testing all of them",
    )
    args = parser.parse_args()

    print(f"pyserial {serial.__version__}")
    print(f"port={args.port}  payload={args.bytes} B  trials={args.trials}\n")

    payload = os.urandom(args.bytes)
    best = None
    results = []

    for baud in BAUDS:
        line_rate = baud / 10 / 1000  # kB/s at 8N1
        print(f"{baud:>9} baud (line max {line_rate:7.1f} kB/s) ... ", end="", flush=True)
        ok, rate, detail = test_baud(args.port, baud, payload, args.trials)
        if ok:
            best = baud
            print(f"OK   {rate / 1000:7.1f} kB/s ({rate / (baud / 10):.0%} of line rate)")
            results.append((baud, "OK"))
        else:
            print("FAIL")
            results.append((baud, "FAIL"))
        if detail:
            print(detail if detail.endswith("\n") else detail + "\n", end="")
        if not ok and args.stop_on_fail:
            print("    stopping at first failure (--stop-on-fail)")
            break

    print("\n--- summary ---")
    for baud, status in results:
        print(f"  {baud:>9} {status}")

    if best is None:
        print("\nNo baud rate worked. Check the loopback wiring (TX->RX) and port name.")
        return 1

    print(f"\nMax error-free baud rate: {best}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
