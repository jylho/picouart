import pytest

from loopback import BAUDS, FRAME_SIZES
from ports import resolve_port


def pytest_addoption(parser):
    parser.addoption(
        "--port",
        default=None,
        help="serial port with a TX-RX loopback, e.g. COM11 or /dev/ttyACM0 "
             "(default: PICOUART_PORT, .env, then USB auto-detection)",
    )
    parser.addoption("--bytes", type=int, default=4096, help="payload size per trial")
    parser.addoption("--trials", type=int, default=3, help="write/read round trips per baud")
    parser.addoption("--max-baud", type=int, default=None, help="skip rates above this")
    parser.addoption("--latency-baud", type=int, default=115200, help="baud rate used for latency tests")
    parser.addoption("--latency-iterations", type=int, default=50, help="round trips timed per frame size")
    parser.addoption(
        "--max-latency-ms",
        type=float,
        default=10.0,
        help="fail if the median round trip exceeds this (FTDI defaults to a 16 ms latency timer)",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "hardware: requires a serial port with a loopback")

    # Resolve once, so every test sees the same port and detection runs once.
    try:
        config.picouart_port = resolve_port(config.getoption("--port"))
        config.picouart_port_error = None
    except RuntimeError as exc:
        config.picouart_port = None
        config.picouart_port_error = str(exc)


def pytest_collection_modifyitems(config, items):
    """Skip hardware tests when no port is available, so a bare `pytest` passes."""
    if config.picouart_port:
        return
    skip = pytest.mark.skip(reason="no serial port (pass --port, set PICOUART_PORT, or attach a Pico)")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def port(request):
    if not request.config.picouart_port:
        pytest.skip(request.config.picouart_port_error or "no serial port")
    return request.config.picouart_port


@pytest.fixture(scope="session")
def trials(request):
    return request.config.getoption("--trials")


@pytest.fixture(scope="session")
def payload(request):
    """One random payload for the whole session, so every baud sees the same data."""
    from loopback import make_payload

    return make_payload(request.config.getoption("--bytes"))


@pytest.fixture(scope="session")
def latency_baud(request):
    return request.config.getoption("--latency-baud")


@pytest.fixture(scope="session")
def latency_iterations(request):
    return request.config.getoption("--latency-iterations")


@pytest.fixture(scope="session")
def max_latency_ms(request):
    return request.config.getoption("--max-latency-ms")


def pytest_generate_tests(metafunc):
    """Parametrize over baud rates and frame sizes, one test each."""
    if "baud" in metafunc.fixturenames:
        cap = metafunc.config.getoption("--max-baud")
        bauds = [b for b in BAUDS if cap is None or b <= cap]
        metafunc.parametrize("baud", bauds, ids=[f"{b}baud" for b in bauds])

    if "frame_size" in metafunc.fixturenames:
        metafunc.parametrize(
            "frame_size", FRAME_SIZES, ids=[f"{n}B" for n in FRAME_SIZES]
        )
