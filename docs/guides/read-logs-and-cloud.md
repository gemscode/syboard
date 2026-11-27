---
version: 0.2.0
updated: 2026-11-27
---

# Read a machine's log and its cloud server

Version 0.2.0 · Updated November 27, 2026

When a node stops answering or misbehaves, two read-only commands tell you what happened: `syboard node journal` reads the
machine's own log, and `syboard cloud` reads the server as Hetzner Cloud sees it.

## Read the machine's log

```bash
syboard node journal 203.0.113.10 --ssh-key ~/.ssh/my-node --since "2026-01-31 08:50:00" --until "2026-01-31 09:10:00"
```

The output starts with the machine's boot time, its uptime and its recent boots, then the log lines of the window. Give
`--since` and `--until` in UTC.

- `--grep PATTERN` keeps only the lines whose message matches the pattern (1 to 80 letters, digits, spaces and `_ . : / | ( ) -`).
- `--lines N` shows the newest N lines of the window, 1 to 2000 (default 200).
- `--json` prints the result as JSON.

Values that look like secrets, such as tokens, passwords and API keys, are masked in the lines it prints.

## Read the cloud server

`syboard cloud` reads a Hetzner Cloud server's status, firewalls, recent actions and graphs. It needs an API token of the server's
project:

```bash
export HETZNER_API_KEY=...
syboard cloud node-1
```

You can also keep the token in a `.env` file and name it with `--env-file`. The token is sent only to Hetzner's API address,
`https://api.hetzner.cloud/v1`, in a header, and never printed.

Give the server's name or its public IPv4 address. Choose what to read with `--what`:

| `--what` | What it reads |
|---|---|
| `all` | Everything below (the default). |
| `server` | The status, type, location, addresses, backups and firewalls with their rules. |
| `actions` | The server's recent actions, such as reboots and rebuilds, with their status. |
| `metrics` | The CPU, disk and network graphs between `--start` and `--end`, every `--step` seconds. |

`--end` defaults to now and `--start` to an hour before it, both in UTC. `--step` is 10 to 86400 seconds (default 300).
