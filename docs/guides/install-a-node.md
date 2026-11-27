---
version: 0.2.0
updated: 2026-11-27
---

# Install a node

Version 0.2.0 · Updated November 27, 2026

A Syboard node is a Debian 13 machine that runs the node's stores under Docker: Elasticsearch 8.15.0, Apache AGE (PostgreSQL 16),
NATS 2.10 with JetStream, and Redis. This guide assesses a machine, then installs the node on it.

## Assess the machine

`syboard node plan` signs in over SSH, measures the machine against the [requirements](../reference/requirements.md) and lists the
install steps still to do. It changes nothing.

```bash
syboard node plan 203.0.113.10 --ssh-key ~/.ssh/my-node --name node-1
```

Each line shows one requirement and what was measured:

| Mark | Meaning |
|---|---|
| `ok` | The requirement is met. |
| `warn` | Below the recommendation, or something to look at, such as a listener other than SSH facing the internet. |
| `FAIL` | Below the minimum. The install refuses the machine. |
| `add` | Missing, and the install adds it (Docker). |
| `set` | Not set yet, and the install sets it (the kernel settings). |

The command exits with `1` when the machine is below any minimum.

## Install

Run `syboard node install` without `--apply` first: it prints the same plan and changes nothing. Then install:

```bash
syboard node install 203.0.113.10 --ssh-key ~/.ssh/my-node --name node-1 --apply
```

The install refuses a machine below any minimum and changes nothing on it. Otherwise it runs each step whose own check does not
pass yet:

| Step | What it does |
|---|---|
| `base` | Updates the system's packages, installs `ca-certificates`, `curl`, `unattended-upgrades` and `jq`, and turns on automatic security updates. |
| `sysctl` | Sets `vm.max_map_count` to at least 262144 and `vm.swappiness` to 1. |
| `docker` | Installs Docker Engine and Docker Compose from Docker's own Debian repository. |
| `folders` | Makes the node's folders under `/opt/syboard` and a secrets folder only root reads, with the stores' password made on the machine. |
| `stores` | Writes the stores' Compose file, starts them, and pins the image digests it pulled so every later start uses the same images. |
| `init` | Loads Apache AGE and creates the node's graph, then checks Elasticsearch and NATS JetStream. |
| `listeners` | Checks that only SSH faces the internet. It changes nothing; a public listener is reported. |

Every port of the stores is bound to `127.0.0.1`. The stores' password stays on the machine and is never printed.

### Name the node

`--name` names the node, which also names its NATS server. It is lower-case letters, digits and dashes, 1 to 63 of them, and it
defaults to `syboard-node`. Use the same name with `node verify`.

### Run it again safely

A second install changes nothing, and an install stopped in a step resumes at that step. Each step's result is appended to
`~/.syboard/deployments/<host>.jsonl` on your computer.

### Use your own requirements

`--requirements FILE` replaces the built-in requirements with a JSON file of the same shape, for example to allow a smaller test
machine. The built-in list is in [Node requirements and checklist](../reference/requirements.md).

## Next step

[Verify the node](verify-a-node.md).
