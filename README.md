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
| [loopback_speed.py](loopback_speed.py) | Sweep baud rates over a loopback and report the max error-free rate |
| [patches/0001-enable-uart-fifo.patch](patches/0001-enable-uart-fifo.patch) | The FIFO change applied to the submodule |
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

The script writes random bytes, reads them back, and on failure reports the
first differing offset with hex and binary context, whether the stream was
truncated or picked up extra bytes, whether the driver silently coerced the
baud rate, and the full traceback for driver-level errors. Use `--stop-on-fail`
to stop at the first bad rate instead of testing the whole table.

Run it against your FTDI adapter first, then against the Pico, for a direct
comparison.

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
is also kept as [patches/0001-enable-uart-fifo.patch](patches/0001-enable-uart-fifo.patch).
After a fresh clone, reapply it with:

```sh
git -C external/pico-uart-bridge apply ../../patches/0001-enable-uart-fifo.patch
```

### Possible next step: DMA

FIFOs remove the per-byte interrupt cost, which is the dominant limit. A DMA
ring buffer for RX would remove the remaining interrupt overhead, but it needs
polling of the DMA write pointer plus the RX-timeout interrupt to detect
trailing bytes, and in practice USB CDC throughput (~1 MB/s on a Pico) becomes
the bottleneck first. Measure with the loopback test before adding it.

## Licenses

The firmware submodule is MIT-licensed by its authors; see
`external/pico-uart-bridge/LICENSE.md`.
