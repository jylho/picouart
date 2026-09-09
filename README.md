# picouart

A fast USB-to-UART bridge built from a Raspberry Pi Pico, as a replacement for
slow FTDI adapters.

Cheap FTDI/CH340/CP210x adapters usually top out well below their advertised
baud rate, and many silently corrupt data instead of reporting an error. This
project flashes a Pico with [pico-uart-bridge][bridge] (patched to enable the
UART hardware FIFOs) and ships a loopback test that measures the *actual*
error-free ceiling of whichever adapter you point it at.

[bridge]: https://github.com/Noltari/pico-uart-bridge

## What's here

| Path | Purpose |
| --- | --- |
| [deploy.ps1](deploy.ps1) | Build + flash the firmware on Windows |
| [deploy.sh](deploy.sh) | Build + flash the firmware on Linux/macOS |
| [release.ps1](release.ps1) | Build a clean image and publish it as a GitHub release |
| [loopback.py](loopback.py) | Loopback measurement logic, shared by the CLI and the tests |
| [ports.py](ports.py) | Port selection: `.env`, environment, USB auto-detection |
| [loopback_speed.py](loopback_speed.py) | Sweep baud rates over a loopback and report the max error-free rate |
| [tests/](tests) | The same checks as a pytest suite, plus small-frame latency |
| [patches/](patches) | Changes applied to the submodule automatically at build time |
| `external/pico-uart-bridge/` | Upstream firmware (git submodule) |

## Hardware

The Pico exposes **two** independent bridges over a single USB cable:

| Interface | TX | RX | Appears as (Linux) | Appears as (Windows) |
| --- | --- | --- | --- | --- |
| UART0 | GP16 | GP17 | `/dev/ttyACM0` | first new COM port |
| UART1 | GP4 | GP5 | `/dev/ttyACM1` | second new COM port |

The onboard LED lights while a host has a CDC port open.

Ground must be common between the Pico and the device you are talking to.
The Pico's UART pins are **3.3 V only** and are not 5 V tolerant.

## Build and flash

Clone with submodules:

```sh
git clone --recurse-submodules <this repo>
```

If you already cloned without them, the deploy scripts will initialize the
vendored SDK for you on first run (it is a large download).

### Windows

Requires the [Raspberry Pi Pico VS Code extension][ext] — the scripts reuse the
compiler, CMake, Ninja, and picotool it installs under `~/.pico-sdk`, so there
is nothing else to install.

[ext]: https://marketplace.visualstudio.com/items?itemName=raspberry-pi.raspberry-pi-pico

```powershell
.\deploy.ps1
```

### Linux / macOS

```sh
sudo apt install cmake ninja-build gcc-arm-none-eabi \
     libnewlib-arm-none-eabi libstdc++-arm-none-eabi-newlib build-essential git
./deploy.sh
```

### Options

Both scripts accept the same switches:

| Windows | Linux | Effect |
| --- | --- | --- |
| `-Board pico_w` | `--board pico_w` | Target a different board |
| `-Clean` | `--clean` | Wipe the build directory first |
| `-BuildOnly` | `--build-only` | Compile without flashing |

Flashing uses `picotool` when available, which reboots an already-running board
into BOOTSEL automatically. Otherwise the script waits for you to hold BOOTSEL
while replugging, then copies the `.uf2` to the `RPI-RP2` drive.

## Measuring the real speed

Jumper the UART's TX to its own RX (GP16↔GP17 for UART0), then:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python loopback_speed.py --port COM11
```

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python loopback_speed.py --port /dev/ttyACM0
```

### Choosing the port

Port names are not stable — `COM11` depends on enumeration order and moves when
devices are replugged. `--port` is therefore optional, and the port is resolved
in this order:

1. an explicit `--port`
2. the `PICOUART_PORT` environment variable
3. `PICOUART_PORT` in a `.env` file in the repo root
4. auto-detection of an attached Pico by USB VID:PID

So the usual setup is once:

```sh
cp .env.example .env     # then edit PICOUART_PORT
```

after which `python loopback_speed.py` and `pytest` need no arguments. `.env`
is gitignored. Use `--port auto` to force detection even when `.env` is set.

To see what is attached, with known adapters named:

```sh
python loopback_speed.py --list-ports
```

```
  COM11  Raspberry Pi Pico (pico-uart-bridge)
  COM12  Raspberry Pi Pico (pico-uart-bridge)
  COM9   FTDI FT232
```

Auto-detection deliberately fails rather than guessing when several boards are
attached, and lists the candidates.

The script writes random bytes, reads them back, and on failure reports the
first differing offset with hex and binary context, whether the stream was
truncated or picked up extra bytes, whether the driver silently coerced the
baud rate, and the full traceback for driver-level errors. Use `--stop-on-fail`
to stop at the first bad rate instead of testing the whole table.

Run it against your FTDI adapter first, then against the Pico, for a direct
comparison.

### As a test suite

The same checks are also a pytest suite, one test per baud rate, which is
handier for regression runs and CI-style reporting:

```sh
pytest --port COM11                          # all rates
pytest --max-baud 1000000                    # port from .env or auto-detect
pytest -v --junitxml=report.xml              # throughput in the XML
```

Options: `--port`, `--bytes`, `--trials`, `--max-baud`.

Tests that need hardware are marked `hardware` and are skipped automatically
when no port can be resolved, so a bare `pytest` still runs the pure-data tests
and passes.

### Latency

Throughput is only half the story. An adapter can stream megabytes per second
and still take 16 ms to turn around a single byte, which is what
request/response protocols actually feel. FTDI parts ship with a **16 ms
latency timer** by default, capping them near 60 transactions/sec no matter
what baud rate you set.

```sh
pytest tests/test_latency.py
pytest tests/test_latency.py --latency-baud 921600
```

Each frame size from 1 to 64 bytes is timed over many round trips, reporting
best, median, worst, and the overhead above the unavoidable wire time. (Wire
time counts once, not twice: a loopback is full duplex, so the return trip
overlaps the outbound one.) Two things are asserted: the median stays under
`--max-latency-ms` (10 ms by default, which a stock FTDI fails and the Pico
passes), and latency does not grow with frame size beyond the extra wire time —
if it does, something is chunking the stream.

For reference, the patched Pico bridge at 115200 baud:

| Frame | Median | Wire time | Overhead |
| --- | --- | --- | --- |
| 1 B | 0.47 ms | 0.09 ms | 0.39 ms |
| 8 B | 0.83 ms | 0.69 ms | 0.14 ms |
| 64 B | 5.74 ms | 5.56 ms | 0.19 ms |

Overhead stays around 0.2 ms regardless of frame size, versus the 16 ms an
FTDI's default latency timer adds to every transaction.

Options: `--latency-baud`, `--latency-iterations`, `--max-latency-ms`.

## Publishing a release

Prebuilt `.uf2` images are attached to [GitHub releases][releases] so users can
flash without installing a toolchain.

[releases]: https://github.com/jylho/picouart/releases

Requires the [GitHub CLI][gh], authenticated once:

[gh]: https://cli.github.com/

```powershell
winget install --id GitHub.cli
gh auth login
```

Then, from a clean working tree:

```powershell
.\release.ps1 -Version v0.1.0
```

[release.ps1](release.ps1) is the whole process in one command: it pushes the
current branch, does a clean build, names the artifact
`picouart-<version>-<board>.uf2`, writes `SHA256SUMS.txt`, creates the tag
pinned to `HEAD`, and uploads everything.

It refuses to run if the working tree is dirty, if the FIFO patch is missing,
or if the tag already exists, so a release always matches its source. Use
`-Draft` to review before publishing, `-Board pico,pico_w` to ship images for
several boards, or `-NoPush` if the branch is already pushed.

## The FIFO patch

Upstream runs the RP2040 UARTs with hardware FIFOs **disabled**, taking one
interrupt per received byte. Above roughly 1 Mbaud the RX interrupt cannot keep
up and bytes are silently dropped. The patch:

- enables the 32-entry FIFOs with the RX trigger at 1/2 full,
- arms the RX-timeout interrupt (`RTIM`), which is required with a FIFO so that
  a burst smaller than the trigger level is still flushed when the line goes
  idle,
- arms and acknowledges the overrun interrupt (`OEIM`/`OEIC`) so an overrun
  cannot wedge the handler.

Submodule working-tree edits are not tracked by this repository, so the change
lives in [patches/0001-enable-uart-fifo.patch](patches/0001-enable-uart-fifo.patch)
instead. **The deploy scripts apply it automatically on every build**, skipping
it when it is already applied, so a fresh clone builds patched firmware without
any manual step.

To go back to unpatched upstream:

```sh
git -C external/pico-uart-bridge checkout -- .
```

(The next build will simply re-apply it.)

### Possible next step: DMA

FIFOs remove the per-byte interrupt cost, which is the dominant limit. A DMA
ring buffer for RX would remove the remaining interrupt overhead, but it needs
polling of the DMA write pointer plus the RX-timeout interrupt to detect
trailing bytes, and in practice USB CDC throughput (~1 MB/s on a Pico) becomes
the bottleneck first. Measure with the loopback test before adding it.

## Licenses

The firmware submodule is MIT-licensed by its authors; see
`external/pico-uart-bridge/LICENSE.md`.
