"""Find the max error-free baud rate on a serial loopback (TX tied to RX).

Reports exactly what goes wrong at each baud: short reads, byte-mismatch
offsets with hex context, coerced baudrates, and full exception tracebacks.

Usage:
    python loopback_speed.py [--port COM11] [--bytes 4096] [--trials 3]

Without --port the port comes from PICOUART_PORT, a .env file, or USB
auto-detection - see ports.py.

For pass/fail output instead, see tests/ (pytest --port COM11).
"""

import argparse
import sys

import serial

from loopback import BAUDS, check_baud, make_payload
from ports import list_candidates, resolve_port


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        default=None,
        help="serial port, or 'auto' to force USB detection "
             "(default: PICOUART_PORT, .env, then auto-detect)",
    )
    parser.add_argument("--bytes", type=int, default=4096, help="payload size per trial")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="list attached serial ports and exit",
    )
    parser.add_argument(
        "--stop-on-fail",
        action="store_true",
        help="stop at the first failing baud rate instead of testing all of them",
    )
    args = parser.parse_args()

    if args.list_ports:
        print("\n".join(list_candidates()))
        return 0

    try:
        port = resolve_port(args.port)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    print(f"pyserial {serial.__version__}")
    print(f"port={port}  payload={args.bytes} B  trials={args.trials}\n")

    payload = make_payload(args.bytes)
    best = None
    results = []

    for baud in BAUDS:
        print(f"{baud:>9} baud (line max {baud / 10 / 1000:7.1f} kB/s) ... ", end="", flush=True)
        r = check_baud(port, baud, payload, args.trials)
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
