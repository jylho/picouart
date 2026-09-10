"""Loopback tests.

The mismatch-reporting logic is tested with plain data and always runs.
The serial tests need real hardware and only run with --port:

    pytest --port COM11
    pytest --port /dev/ttyACM0 --max-baud 1000000
"""

import pytest

from loopback import Result, check_baud, describe_mismatch


class TestDescribeMismatch:
    """Pure-data tests: no hardware required."""

    def test_reports_first_bad_offset(self):
        sent = bytes(range(16))
        got = bytearray(sent)
        got[7] ^= 0x01  # single flipped bit
        text = describe_mismatch(sent, bytes(got))
        assert "first bad byte at offset 7" in text
        assert "1/16 bytes differ" in text

    def test_reports_truncation(self):
        sent = bytes(range(16))
        text = describe_mismatch(sent, sent[:10])
        assert "sent 16 B, got 10 B" in text
        assert "truncated at offset 10" in text

    def test_reports_extra_bytes(self):
        sent = bytes(range(16))
        text = describe_mismatch(sent, sent + b"\x00\x00")
        assert "2 extra byte(s)" in text


class TestResult:
    def test_efficiency_is_fraction_of_line_rate(self):
        # 8N1 spends 10 bits per byte, so 115200 baud caps at 11520 B/s.
        assert Result(115200, True, 11520).efficiency == pytest.approx(1.0)
        assert Result(115200, True, 5760).efficiency == pytest.approx(0.5)


@pytest.mark.hardware
def test_loopback_at_baud(port, baud, payload, trials, record_property):
    """Data written to the port must come back byte-identical.

    Throughput is recorded from the same run rather than measured again, so
    `-v` and JUnit XML show the numbers without doubling the time on the wire.
    """
    r = check_baud(port, baud, payload, trials)
    assert r.ok, f"{baud} baud failed on {port}:\n{r.detail}"

    record_property("bytes_per_sec", round(r.throughput))
    record_property("efficiency", round(r.efficiency, 3))
