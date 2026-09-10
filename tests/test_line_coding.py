"""Does the bridge really apply the requested baud rate and line coding?

A loopback shares a single UART, so TX and RX always agree with each other.
If the firmware ignored the requested settings and stayed at its power-on
default, every byte-for-byte check in test_loopback.py would still pass.

Timing is what actually proves it. The wire spends a fixed number of bits per
byte -- 1 start + 8 data + optional parity + stop bits -- so the elapsed time
of a large transfer says what the line really did:

    8N1  10 bits/byte   baseline
    8E1  11 bits/byte   ~10% slower
    8O1  11 bits/byte   ~10% slower
    8N2  11 bits/byte   ~10% slower

Needs hardware:

    pytest tests/test_line_coding.py
"""

import pytest

from loopback import bits_per_byte, timed_transfer

# Large enough that transfer time dominates USB and scheduling overhead.
PAYLOAD_SIZE = 8192

# Timing on a general-purpose OS is noisy, so allow a generous band. It is
# still far tighter than the difference between adjacent baud rates (2x) or
# between line codings (10%).
TOLERANCE = 0.15


@pytest.fixture(scope="module")
def coding_payload():
    """Every byte value, so no pattern is accidentally parity-friendly."""
    return bytes(range(256)) * (PAYLOAD_SIZE // 256)


class TestBitsPerByte:
    """Pure-data tests: no hardware required."""

    def test_8n1_is_ten_bits(self):
        assert bits_per_byte("N", 1) == 10

    def test_parity_adds_one_bit(self):
        assert bits_per_byte("E", 1) == 11
        assert bits_per_byte("O", 1) == 11

    def test_second_stop_bit_adds_one_bit(self):
        # 1 start + 8 data + 2 stop = 11, not 12.
        assert bits_per_byte("N", 2) == 11

    def test_parity_and_two_stop_bits(self):
        assert bits_per_byte("E", 2) == 12


@pytest.mark.hardware
@pytest.mark.parametrize("rate", [115200, 230400, 460800, 921600])
def test_baud_rate_is_applied(port, rate, coding_payload, record_property):
    """Transfer time must match the requested baud, not some default."""
    got, elapsed = timed_transfer(port, rate, coding_payload)
    assert got == coding_payload, f"{len(got)}/{len(coding_payload)} B returned"

    implied = len(coding_payload) * bits_per_byte() / elapsed
    ratio = implied / rate
    record_property("implied_baud", round(implied))
    record_property("ratio", round(ratio, 3))

    assert abs(ratio - 1) < TOLERANCE, (
        f"asked for {rate} baud but the wire ran at about {implied:,.0f} "
        f"({ratio:.2f}x). The bridge is not applying the requested rate."
    )


@pytest.mark.hardware
@pytest.mark.parametrize(
    "parity,stopbits",
    [("N", 1), ("E", 1), ("O", 1), ("N", 2), ("E", 2)],
    ids=["8N1", "8E1", "8O1", "8N2", "8E2"],
)
def test_line_coding_is_applied(port, parity, stopbits, coding_payload, record_property):
    """Parity and stop bits must change the time on the wire, not just the API call."""
    rate = 115200
    got, elapsed = timed_transfer(port, rate, coding_payload, parity, stopbits)
    assert got == coding_payload, (
        f"8{parity}{int(stopbits)}: {len(got)}/{len(coding_payload)} B returned"
    )

    expected_bits = bits_per_byte(parity, stopbits)
    implied_bits = elapsed * rate / len(coding_payload)
    record_property("expected_bits_per_byte", expected_bits)
    record_property("implied_bits_per_byte", round(implied_bits, 2))

    # Measured to within about 0.01 bits in practice. An ignored setting is
    # off by a whole bit, so 0.5 separates the two cases with room to spare.
    assert abs(implied_bits - expected_bits) < 0.5, (
        f"8{parity}{int(stopbits)} should spend {expected_bits} bits/byte but "
        f"the wire spent about {implied_bits:.1f}. The setting is being ignored."
    )
