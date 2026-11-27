---
version: 0.2.0
updated: 2026-11-27
---

# Installation

Version 0.2.0 · Updated November 27, 2026

`syboard` is a single executable with no dependencies. Install it on the computer you work from; it reaches each node over SSH.

## System requirements

| System | Executable |
|---|---|
| macOS on Apple silicon | `syboard-macos-arm64` |
| Linux on x86_64 | `syboard-linux-x86_64` |
| Linux on ARM (aarch64) | `syboard-linux-arm64` |

From source, `syboard` needs Python 3.10 or newer and nothing else.

## Install the executable

1. Download the file for your system from the [latest release](https://github.com/gemscode/syboard/releases/latest), with its
   `.sha256` file beside it.
2. Check the download against its SHA-256:

    ```bash
    shasum -a 256 -c syboard-linux-x86_64.sha256
    ```

3. On macOS only, clear the quarantine mark the browser puts on a download (the executable is not signed yet):

    ```bash
    xattr -d com.apple.quarantine ~/Downloads/syboard-macos-arm64
    ```

4. Make it executable and put it on your `PATH` as `syboard`:

    ```bash
    chmod +x syboard-linux-x86_64
    sudo mv syboard-linux-x86_64 /usr/local/bin/syboard
    ```

To install without a browser, for example on a server, download both files with `curl`:

```bash
curl -fLO https://github.com/gemscode/syboard/releases/latest/download/syboard-linux-x86_64
curl -fLO https://github.com/gemscode/syboard/releases/latest/download/syboard-linux-x86_64.sha256
```

## Install from source

```bash
python3 -m pip install git+https://github.com/gemscode/syboard
```

## Check the installation

```bash
syboard --version
```

It prints the version, for example `syboard 0.2.0`.

## Upgrade

Install the newer executable over the old one, the same way. From source, add `--upgrade` to the `pip install` command.

## Uninstall

Remove the executable, for example `sudo rm /usr/local/bin/syboard`, or run `python3 -m pip uninstall syboard`. `syboard` keeps
its records in `~/.syboard/deployments/`; delete that folder too if you no longer need them.
