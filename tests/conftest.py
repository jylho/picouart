import pytest

from loopback import BAUDS


def pytest_addoption(parser):
    parser.addoption("--port", default=None, help="serial port with a TX-RX loopback, e.g. COM11 or /dev/ttyACM0")
    parser.addoption("--bytes", type=int, default=4096, help="payload size per trial")
    parser.addoption("--trials", type=int, default=3, help="write/read round trips per baud")
    parser.addoption("--max-baud", type=int, default=None, help="skip rates above this")


def pytest_configure(config):
    config.addinivalue_line("markers", "hardware: requires a serial port with a loopback")


def pytest_collection_modifyitems(config, items):
    """Skip hardware tests unless --port is given, so a bare `pytest` still passes."""
    if config.getoption("--port"):
        return
    skip = pytest.mark.skip(reason="needs --port (e.g. pytest --port COM11)")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def port(request):
    value = request.config.getoption("--port")
    if not value:
        pytest.skip("no --port given")
    return value


@pytest.fixture(scope="session")
def trials(request):
    return request.config.getoption("--trials")


@pytest.fixture(scope="session")
def payload(request):
    """One random payload for the whole session, so every baud sees the same data."""
    from loopback import make_payload

    return make_payload(request.config.getoption("--bytes"))


def pytest_generate_tests(metafunc):
    """Parametrize over baud rates so each gets its own pass/fail line."""
    if "baud" not in metafunc.fixturenames:
        return
    cap = metafunc.config.getoption("--max-baud")
    bauds = [b for b in BAUDS if cap is None or b <= cap]
    metafunc.parametrize("baud", bauds, ids=[f"{b}baud" for b in bauds])
