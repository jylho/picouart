"""Find the max error-free baud rate on a serial loopback (TX tied to RX).

Reports exactly what goes wrong at each baud: short reads, byte-mismatch
offsets with hex context, coerced baudrates, and full exception tracebacks.

Usage:
    python loopback_speed.py --port COM11 [--bytes 4096] [--trials 3]

For pass/fail output instead, see tests/ (pytest --port COM11).
"""

import argparse
import sys

import serial

from loopback import BAUDS, check_baud, make_payload


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

    payload = make_payload(args.bytes)
    best = None
    results = []

    for baud in BAUDS:
        print(f"{baud:>9} baud (line max {baud / 10 / 1000:7.1f} kB/s) ... ", end="", flush=True)
        r = check_baud(args.port, baud, payload, args.trials)
        if r.ok:
            best = baud
            print(f"OK   {r.throughput / 1000:7.1f} kB/s ({r.efficiency:.0%} of line rate)")
        else:
            print("FAIL")
        results.append(r)

        if r.detail:
            print(r.detail if r.detail.endswith("\n") else r.detail + "\n", end="")
        if not r.ok and args.stop_on_fail:
            print("    stopping at first failure (--stop-on-fail)")
            break

    print("\n--- summary ---")
    for r in results:
        print(f"  {r.baud:>9} {'OK' if r.ok else 'FAIL'}")

    if best is None:
        print("\nNo baud rate worked. Check the loopback wiring (TX->RX) and port name.")
        return 1

    print(f"\nMax error-free baud rate: {best}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
