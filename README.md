# Syboard

Syboard is a governed agent harness that runs on NATS and Elasticsearch. Version 0.1 ships its **node tools**: one
command, `syboard`, that prepares a Linux machine to be a Syboard node and lets you look at it when something goes wrong.

| Command | What it does | Changes the machine |
|---|---|---|
| `syboard node plan` | Assesses a machine over SSH against the node requirements and lists the install steps still to do | No |
| `syboard node install --apply` | Installs Docker and the node's stores (Elasticsearch, Apache AGE, NATS with JetStream, Redis) | Yes |
| `syboard node journal` | Reads the machine's own log over a time window | No |
| `syboard cloud` | Reads a Hetzner Cloud server's status, firewalls, actions and graphs | No |

The governance, the node registry, the agents and the views come in later releases.

## Install

Download the executable for your system from the [latest release](https://github.com/gemscode/syboard/releases/latest),
check it against its `.sha256` file, make it executable and put it on your `PATH`:

```bash
curl -fLO https://github.com/gemscode/syboard/releases/latest/download/syboard-linux-x86_64
curl -fLO https://github.com/gemscode/syboard/releases/latest/download/syboard-linux-x86_64.sha256
shasum -a 256 -c syboard-linux-x86_64.sha256
chmod +x syboard-linux-x86_64 && sudo mv syboard-linux-x86_64 /usr/local/bin/syboard
syboard --version
```

| System | File |
|---|---|
| macOS on Apple silicon | `syboard-macos-arm64` |
| Linux on x86_64 | `syboard-linux-x86_64` |
| Linux on ARM (aarch64) | `syboard-linux-arm64` |

The macOS executable is not signed yet. The first time, macOS may refuse to open a file downloaded from the internet; clear
its quarantine flag once with `xattr -d com.apple.quarantine syboard-macos-arm64`.

To install from source instead (Python 3.10 or newer, no other dependency):

```bash
python3 -m pip install git+https://github.com/gemscode/syboard
```

## A first run

You need a machine running Debian 13 that you can reach over SSH as root with a key.

```bash
# 1. Read the machine against the requirements. Nothing is changed.
syboard node plan 203.0.113.10 --ssh-key ~/.ssh/my-node

# 2. See what the install would do (still nothing is changed), then install.
syboard node install 203.0.113.10 --ssh-key ~/.ssh/my-node --name node-1
syboard node install 203.0.113.10 --ssh-key ~/.ssh/my-node --name node-1 --apply

# 3. If the machine stops answering, read what it logged around that time...
syboard node journal 203.0.113.10 --ssh-key ~/.ssh/my-node --since "2026-01-31 08:50:00" --until "2026-01-31 09:10:00"

# ...or, on Hetzner Cloud, ask the provider how the server looks.
export HETZNER_API_KEY=...   # a Read token from the Hetzner Cloud console, Security, API tokens
syboard cloud node-1
```

`plan` prints one line per requirement: `ok`, `warn` (below the recommended value), `FAIL` (below the minimum), `add`
(the install adds it) or `set` (the install sets it), then the install steps and whether each is done.

## The commands

Every command accepts `--json` to print JSON in place of text, and `--help` for its options.

### `syboard node plan HOST --ssh-key FILE`

Reads the machine over SSH and compares it with the requirements: its operating system, processors, memory, free disk,
architecture, Docker, `vm.max_map_count`, swap, systemd, clock, outbound HTTPS, the stores' local ports, its networks
and what listens on a public address. Then it runs each install step's check and reports which steps are still to do.
It changes nothing. Options: `--user` (default `root`), `--name` (the node's name, default `syboard-node`),
`--requirements FILE` (a JSON list of requirements in place of the built-in ones). It exits with 1 when a requirement is
below its minimum.

### `syboard node install HOST --ssh-key FILE [--apply]`

Without `--apply`, it plans and changes nothing. With `--apply`, it refuses a machine below any minimum, then runs each
step whose check does not pass yet:

1. **base**: the package lists, the system's upgrades, `curl`, `jq` and automatic security updates.
2. **sysctl**: `vm.max_map_count` of at least 262144 (a higher value is kept) and `vm.swappiness=1`, kept across restarts.
3. **docker**: Docker Engine and the Compose plugin from Docker's own Debian repository.
4. **folders**: `/opt/syboard`, with a secrets folder only root can read and a password for the stores made on the machine.
5. **stores**: Elasticsearch 8.15.0, Apache AGE (PostgreSQL 16), NATS with JetStream and Redis as one Compose project,
   every port bound to `127.0.0.1`. The digests of the images pulled the first time are kept, so later starts use the same images.
6. **init**: the AGE extension and a graph named `syboard`; the check asks Elasticsearch for yellow or green, AGE for a
   Cypher query and NATS for JetStream.
7. **listeners**: nothing but SSH listens on a public address.

A second run finds every step done and changes nothing; a run stopped in a step resumes at that step. Each step's result is
appended to `~/.syboard/deployments/HOST.jsonl` on the machine you run `syboard` from.

### `syboard node journal HOST --ssh-key FILE --since UTC --until UTC`

The machine's boot time, its last boots and its journal between the two times (UTC), the newest `--lines` of them
(default 200), only those matching `--grep` when it is given. Values that look like secrets are masked. It changes nothing.

### `syboard cloud SERVER`

A Hetzner Cloud server, found by its name or its public IPv4 address: its status, type, location, addresses, firewalls and
their rules, the provider's actions on it (power, reset, rebuild, backups...) and its graphs (`--what server|actions|metrics`,
default all). The graphs cover `--start` to `--end` in UTC (default: the last hour) every `--step` seconds (default 300;
Hetzner returns the network and disk graphs at five-minute steps). The token comes from `HETZNER_API_KEY` in the
environment, or from a `.env` file given with `--env-file`. A Read token is enough.

## Security

- No key or token is ever printed, logged or written to disk by `syboard`. Tokens travel only in request headers.
- `syboard cloud` sends only GET requests and does not follow redirects, so even a token that allows writes changes nothing through it.
  It sends the token only to `https://api.hetzner.cloud/v1` (a test stand-in only over http on this machine's loopback) and uses no proxy.
- Every command reaches the machine as a script on the standard input of `bash -s` over one SSH connection; nothing is
  quoted on a command line. Values you pass (times, patterns) are checked before anything runs.
- The stores listen on `127.0.0.1` only. Elasticsearch runs without its security layer because nothing outside the machine
  reaches it; keep port 22 the only one open to the internet (`syboard node plan` checks it).
- To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Development

```bash
git clone https://github.com/gemscode/syboard && cd syboard
python tests/test_node.py      # the node tools against a test machine made of stub programs
python tests/test_cloud.py     # the cloud reads against a local stand-in for the Hetzner API
python scripts/leak_scan.py    # no keys, tokens or private key blocks in the repository
python -m syboard --help       # run from the source tree (with PYTHONPATH=src)
```

To build an executable yourself: `pip install pyinstaller` then
`pyinstaller --onefile --name syboard --paths src src/syboard/__main__.py`.
Releases are built by GitHub Actions when a version tag (`v0.1.0`) is pushed.

## Contributing

Contributions are welcome: read [CONTRIBUTING.md](CONTRIBUTING.md). Your first pull request asks you to sign the
[contributor license agreement](docs/CLA.md), and every change needs the maintainer's approving review.

## License

Syboard is licensed under the [Apache License, Version 2.0](LICENSE).
