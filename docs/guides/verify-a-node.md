---
version: 0.2.0
updated: 2026-11-27
---

# Verify a node

Version 0.2.0 · Updated November 27, 2026

`syboard node verify` checks a node against its checklist and changes nothing on it. Use it after an install, after a restart, or
whenever something looks wrong.

```bash
syboard node verify 203.0.113.10 --ssh-key ~/.ssh/my-node --name node-1
```

## What it checks

The checklist has six modules: the machine with Docker, the node's secrets, Elasticsearch, Apache AGE, NATS with JetStream and
Redis. Each module is checked at three levels:

| Level | What passes |
|---|---|
| present | Its containers exist and its files are in place. |
| running | Its containers are up and healthy, unchanged over the settle window and not restarted since the last verify. |
| working | A real read that a person's use of the module depends on passes, such as Elasticsearch's health or a Cypher query on AGE. |

One more row, `coverage`, checks that every container on the machine belongs to a module. The full list of checks is in
[Node requirements and checklist](../reference/requirements.md).

`node verify` only reads. It sends one survey script over SSH, reads names, modes and owners of the secrets but never their values,
and writes nothing on the node.

## Read the report

The first line names the node and how many rows pass. Then each row shows its module and its three levels. Under a row that does
not pass, each failed check is listed with what it found, followed by the module's fix, for example
`fix: syboard node install --apply (steps stores, init)`.

The command exits with `0` when every row passes, and `1` otherwise.

## Check one module

```bash
syboard node verify 203.0.113.10 --ssh-key ~/.ssh/my-node --name node-1 --module store-elasticsearch
```

A one-module run doesn't replace the last full run, which stays the baseline for the containers' restart counts.

## The records it keeps

Each run appends one record per module, and a summary for a full run, to `~/.syboard/deployments/<host>.jsonl` on your computer.
The next run reads the restart counts there, so a container that restarted between two runs fails its `running` level.

## Safety check before any check

A machine whose `stores/node.env` does not name the node is refused before any check, so you never verify the wrong node by mistake.
Nothing is recorded for a refused run.

## Use your own checklist

`--checklist FILE` replaces the built-in checklist with a JSON file of the same shape.
