---
version: 0.2.0
updated: 2026-11-27
---

# Quickstart

Version 0.2.0 · Updated November 27, 2026

In this quickstart you turn a fresh Debian 13 machine into a Syboard node and check that it works. It takes four commands; most of
the time goes to downloading Docker and the stores' images.

## Before you begin

You need:

- `syboard` installed on your computer. See [Installation](installation.md).
- A machine running Debian 13 with at least 4 vCPU, 8 GiB of memory and 100 GB of free disk. See the full
  [requirements](../reference/requirements.md).
- SSH access to that machine as `root` with a private key, for example `~/.ssh/my-node`.

The examples use `203.0.113.10` for the machine's address and `node-1` for the node's name. Replace them with yours.

## Step 1: Assess the machine

Read the machine against the requirements. This changes nothing on it.

```bash
syboard node plan 203.0.113.10 --ssh-key ~/.ssh/my-node --name node-1
```

Each requirement is printed on one line, marked `ok`, `warn`, `FAIL`, `add` (the install adds it) or `set` (the install sets it).
The last line lists the install steps still to do. If a line reads `refused: below the minimum for ...`, the machine is too small
or the wrong system; fix that before you go on.

## Step 2: Install the node

Without `--apply`, `node install` shows the same plan and changes nothing. Run it with `--apply` to install:

```bash
syboard node install 203.0.113.10 --ssh-key ~/.ssh/my-node --name node-1 --apply
```

The install runs seven steps over one SSH connection: `base`, `sysctl`, `docker`, `folders`, `stores`, `init` and `listeners`. Each
step prints its result as it ends. When all are done you see:

```text
installed: every step done on 203.0.113.10 (... commands over one SSH connection)
```

You can run the install again at any time. A step that is already done is skipped, and a run that stopped partway resumes at the
step where it stopped.

## Step 3: Verify the node

Check every module of the node at three levels: present, running and working. This changes nothing on it.

```bash
syboard node verify 203.0.113.10 --ssh-key ~/.ssh/my-node --name node-1
```

The command exits with `0` when every check passes. A failing row names the module, the level and the fix.

## Step 4: Read the machine's log when something goes wrong

If the machine stopped answering, read what it logged around that time. Times are UTC:

```bash
syboard node journal 203.0.113.10 --ssh-key ~/.ssh/my-node --since "2026-01-31 08:50:00" --until "2026-01-31 09:10:00"
```

## Next steps

- [Verify a node](../guides/verify-a-node.md): what each check reads, and how to check one module.
- [Read a machine's log and its cloud server](../guides/read-logs-and-cloud.md): filter the log, and read a Hetzner Cloud server.
- [CLI reference](../reference/cli.md): every command and option.
