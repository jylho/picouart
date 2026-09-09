"""Small-frame round-trip latency.

Throughput and latency are independent: an adapter can stream megabytes per
second and still take 16 ms to turn around a single byte, which is what
request/response protocols actually feel. FTDI parts ship with a 16 ms latency
timer by default, capping them near 60 transactions/sec at any baud rate.

Needs hardware:

    pytest tests/test_latency.py --port COM11
    pytest tests/test_latency.py --port COM11 --latency-baud 921600
"""

import pytest

from loopback import Latency, measure_latency


class TestLatencyMath:
    """Pure-data tests: no hardware required."""

    def test_wire_time_matches_8n1(self):
        # 10 bits per byte at 115200 baud -> 64 B takes ~5.56 ms.
        assert Latency(115200, 64).wire_ms == pytest.approx(5.5555, abs=1e-3)

    def test_overhead_excludes_both_directions(self):
        # A loopback crosses the wire twice, so subtract 2x wire time.
        lat = Latency(115200, 64, samples=[20.0])
        assert lat.overhead == pytest.approx(20.0 - 2 * lat.wire_ms)

    def test_jitter_is_spread(self):
        assert Latency(115200, 1, samples=[1.0, 4.0, 2.0]).jitter == 3.0


@pytest.mark.hardware
def test_small_frame_round_trip(port, frame_size, latency_baud, latency_iterations, max_latency_ms, record_property):
    """A small frame must come back promptly, not just eventually."""
    lat = measure_latency(port, latency_baud, frame_size, latency_iterations)
    assert lat.ok, f"{frame_size} B frame failed:\n{lat.detail}"

    record_property("median_ms", round(lat.median, 3))
    record_property("best_ms", round(lat.best, 3))
    record_property("worst_ms", round(lat.worst, 3))
    record_property("overhead_ms", round(lat.overhead, 3))

    assert lat.median <= max_latency_ms, (
        f"{frame_size} B at {latency_baud} baud: median {lat.median:.2f} ms "
        f"exceeds {max_latency_ms} ms "
        f"(best {lat.best:.2f}, worst {lat.worst:.2f}, "
        f"wire time only {lat.wire_ms:.3f} ms). "
        "On FTDI this is usually the 16 ms latency timer."
    )


@pytest.mark.hardware
def test_latency_is_dominated_by_overhead_not_baud(port, latency_baud, latency_iterations):
    """Small frames should cost about the same regardless of size.

    If latency scaled with frame size, the line would be the bottleneck. For
    frames this small it is the adapter's turnaround, so 1 B and 64 B should
    land close together. A large gap means something is chunking the stream.
    """
    small = measure_latency(port, latency_baud, 1, latency_iterations)
    large = measure_latency(port, latency_baud, 64, latency_iterations)
    assert small.ok and large.ok, f"{small.detail}{large.detail}"

    extra_wire_ms = 2 * (large.wire_ms - small.wire_ms)
    growth = large.median - small.median
    assert growth <= extra_wire_ms + 5.0, (
        f"64 B took {growth:.2f} ms longer than 1 B, but only "
        f"{extra_wire_ms:.2f} ms of that is wire time"
    )
