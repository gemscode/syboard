---
version: 0.2.0
---

# CLI reference

Version 0.2.0 · Generated from the `syboard` command's own parser by `scripts/gen_docs_reference.py`.

The `syboard` command has two command groups: `node` works on a node's machine over SSH, and `cloud` reads a Hetzner Cloud server. Every command prints text, or JSON with `--json`. `syboard --version` prints the version, and `syboard <command> --help` prints a command's help.

## Commands

| Command | Description | Example |
|---|---|---|
| `syboard node plan` | Assess the machine and list the steps still to do (read only) | `syboard node plan 203.0.113.10 --ssh-key ~/.ssh/my-node` |
| `syboard node install` | Install the node's stores; plans only, unless --apply is given | `syboard node install 203.0.113.10 --ssh-key ~/.ssh/my-node --name node-1 --apply` |
| `syboard node verify` | Check the node against its checklist: each module present, running and working (read only) | `syboard node verify 203.0.113.10 --ssh-key ~/.ssh/my-node --name node-1` |
| `syboard node journal` | The machine's own log over a window (read only) | `syboard node journal 203.0.113.10 --ssh-key ~/.ssh/my-node --since "2026-01-31 08:50:00" --until "2026-01-31 09:10:00"` |
| `syboard cloud` | A Hetzner Cloud server's status, firewalls, actions and graphs (read only) | `syboard cloud node-1 --what server` |

## Options of each command

### syboard node plan

Assess the machine and list the steps still to do (read only).

```
usage: syboard node plan [-h] --ssh-key SSH_KEY [--user USER] [--name NAME]
                         [--requirements REQUIREMENTS] [--json]
                         host
```

| Option | Description | Required | Default |
|---|---|---|---|
| `<host>` | the machine's address or host name | yes |  |
| `--ssh-key <ssh-key>` | the private key that signs in to the machine | yes |  |
| `--user <user>` | the user to sign in as (default root) |  | `root` |
| `--name <name>` | the node's name, used for its NATS server (default syboard-node) |  |  |
| `--requirements <requirements>` | a JSON file of requirements in place of the built-in ones |  |  |
| `--json` | print JSON |  |  |

### syboard node install

Install the node's stores; plans only, unless --apply is given.

```
usage: syboard node install [-h] --ssh-key SSH_KEY [--user USER] [--name NAME]
                            [--requirements REQUIREMENTS] [--json] [--apply]
                            host
```

| Option | Description | Required | Default |
|---|---|---|---|
| `<host>` | the machine's address or host name | yes |  |
| `--ssh-key <ssh-key>` | the private key that signs in to the machine | yes |  |
| `--user <user>` | the user to sign in as (default root) |  | `root` |
| `--name <name>` | the node's name, used for its NATS server (default syboard-node) |  |  |
| `--requirements <requirements>` | a JSON file of requirements in place of the built-in ones |  |  |
| `--json` | print JSON |  |  |
| `--apply` | make the changes (without it, nothing is changed) |  |  |

### syboard node verify

Check the node against its checklist: each module present, running and working (read only).

```
usage: syboard node verify [-h] --ssh-key SSH_KEY [--user USER] [--name NAME]
                           [--module MODULE] [--checklist CHECKLIST] [--json]
                           host
```

| Option | Description | Required | Default |
|---|---|---|---|
| `<host>` | the machine's address or host name | yes |  |
| `--ssh-key <ssh-key>` | the private key that signs in to the machine | yes |  |
| `--user <user>` | the user to sign in as (default root) |  | `root` |
| `--name <name>` | the node's name, as given to node install (default syboard-node) |  |  |
| `--module <module>` | check this module only (the last full run stays the restart baseline) |  |  |
| `--checklist <checklist>` | a JSON checklist in place of the built-in one |  |  |
| `--json` | print JSON |  |  |

### syboard node journal

The machine's own log over a window (read only).

```
usage: syboard node journal [-h] --ssh-key SSH_KEY [--user USER] --since SINCE
                            --until UNTIL [--grep GREP] [--lines LINES]
                            [--json]
                            host
```

| Option | Description | Required | Default |
|---|---|---|---|
| `<host>` | the machine's address or host name | yes |  |
| `--ssh-key <ssh-key>` | the private key that signs in to the machine | yes |  |
| `--user <user>` | the user to sign in as (default root) |  | `root` |
| `--since <since>` | UTC, such as 2026-01-31 08:30:00 | yes |  |
| `--until <until>` | UTC, such as 2026-01-31 09:00:00 | yes |  |
| `--grep <grep>` | only the lines whose message matches this pattern |  |  |
| `--lines <lines>` | the newest lines to show (1 to 2000, default 200) |  | `200` |
| `--json` | print JSON |  |  |

### syboard cloud

A Hetzner Cloud server's status, firewalls, actions and graphs (read only).

```
usage: syboard cloud [-h] [--what {all,server,actions,metrics}]
                     [--start START] [--end END] [--step STEP]
                     [--env-file ENV_FILE] [--json]
                     server
```

| Option | Description | Required | Default |
|---|---|---|---|
| `<server>` | the server's name, or its public IPv4 address | yes |  |
| `--what <what>` | what to read (default all); one of `all`, `server`, `actions`, `metrics` |  | `all` |
| `--start <start>` | the graphs' start, UTC (default: an hour before --end) |  |  |
| `--end <end>` | the graphs' end, UTC (default: now) |  |  |
| `--step <step>` | seconds between graph points (default 300) |  | `300` |
| `--env-file <env-file>` | a .env file that holds HETZNER_API_KEY (default: the environment variable) |  |  |
| `--json` | print JSON |  |  |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | The command did what it was asked: the plan was shown, every install step is done, every check passed, or the log or server was read. |
| `1` | The command was refused or failed: a missing SSH key, an invalid name, a machine below the minimum, a check that did not pass, a machine that did not answer, or records that could not be written. The reason is printed on standard error. |
| `2` | The command line itself was wrong: an unknown command or a missing required option. |
| `130` | Interrupted with Ctrl-C. |

## Environment

| Variable | Used by | What it holds |
|---|---|---|
| `HETZNER_API_KEY` | `syboard cloud` | The Hetzner Cloud API token, read from the environment or from the file `--env-file` names. It is sent only to Hetzner's API address. |

## Files

| Path | Written by | What it holds |
|---|---|---|
| `~/.syboard/deployments/<host>.jsonl` | `node install --apply`, `node verify` | One JSON record per install step and per verified module, with a summary per full verify run. The next `node verify` reads the containers' restart counts from it. |
