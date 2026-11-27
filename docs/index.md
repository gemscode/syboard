---
version: 0.2.0
updated: 2026-11-27
---

# Syboard documentation

Version 0.2.0 · Updated November 27, 2026

!!! tip "Ask the documentation chat"
    Have a question about Syboard? Ask the documentation chat at
    [sideborg.app/documentation/chat](https://sideborg.app/documentation/chat).

Syboard is a governed agent harness that runs on NATS and Elasticsearch. Version 0.2 ships its node tools: one command,
`syboard`, that prepares a Linux machine to be a Syboard node, checks the node against its checklist, and helps you look at it
when something goes wrong.

## Install

Download the executable for your system from the [latest release](https://github.com/gemscode/syboard/releases/latest), or
install from source with Python 3.10 or newer:

```bash
python3 -m pip install git+https://github.com/gemscode/syboard
```

See [Installation](get-started/installation.md) for each system and how to check the download.

## Get started

- [Quickstart](get-started/quickstart.md): prepare, install and verify your first node with four commands.
- [Installation](get-started/installation.md): install `syboard` on macOS or Linux, check it, upgrade it or remove it.

## Use Syboard

- [Install a node](guides/install-a-node.md): assess a machine, then install Docker and the node's stores on it.
- [Verify a node](guides/verify-a-node.md): check each module of a node at three levels, present, running and working.
- [Read a machine's log and its cloud server](guides/read-logs-and-cloud.md): find out what happened on a node, and how its
  cloud provider sees it.

## Reference

- [CLI reference](reference/cli.md): every command, option, exit code, environment variable and file.
- [Node requirements and checklist](reference/requirements.md): what a machine needs, and what `node verify` checks.

## Resources

- [Troubleshooting](resources/troubleshooting.md): common errors and how to fix them.
- [Release notes](release-notes.md): what changed in each version.
- [Contributing](https://github.com/gemscode/syboard/blob/main/CONTRIBUTING.md),
  [security policy](https://github.com/gemscode/syboard/blob/main/SECURITY.md) and
  [license](https://github.com/gemscode/syboard/blob/main/LICENSE) (Apache 2.0).
