# Changelog

The changes in each version of Syboard's node tools, newest first. Each version is tagged `vX.Y.Z`, and the release of that tag
carries the executables with their SHA-256.

## Unreleased

### Added

- The documentation in `docs/`: an overview, a quickstart, the installation, guides to install, verify and read a node, the CLI
  reference, the node's requirements and checklist, troubleshooting and these release notes, with `mkdocs.yml` to build it as a
  site. `scripts/gen_docs_reference.py` writes the reference pages and the release notes from the code; with `--check` it fails when
  they are out of date.
- `syboard --help` ends with where the documentation is, and `syboard node journal` and `syboard cloud` give every option a help line.

## 0.2.0 (2026-11-25)

### Added

- `syboard node verify HOST --ssh-key FILE`: checks a node against its checklist and changes nothing on it. Each module of the
  checklist (the machine with Docker, the node's secrets, Elasticsearch, Apache AGE, NATS with JetStream and Redis) is checked at
  three levels, present, running and working, and one more row checks that every container belongs to a module. A machine whose
  `stores/node.env` names another node is refused before any check. Options: `--user`, `--name`, `--module`, `--checklist`,
  `--json`. Each run appends one record per module and a summary to `~/.syboard/deployments/HOST.jsonl`, where the next run reads
  the containers' restart counts.
- The node's checklist, `CHECKLIST` in `src/syboard/resources.py`; a JSON file of the same shape replaces it with `--checklist`.
- `tests/test_verify.py`: a node made by `syboard node install --apply` on the test machine passes `node verify`, every fault in
  a survey's output crosses its own row and level only, and the command keeps its records and its baseline. CI runs it.

### Changed

- The test machine of `tests/test_node.py` also answers `stat`, `df -P`, `docker inspect`, `redis-cli PING` and a search on
  Elasticsearch, and its `timeout` runs the command it limits.

## 0.1.1 (2026-11-24)

### Fixed

- `syboard cloud` sends the Hetzner token only to `https://api.hetzner.cloud/v1` (a test stand-in only over http on this
  machine's loopback) and uses no proxy.

## 0.1.0 (2026-11-24)

### Added

- `syboard node plan`, `syboard node install`, `syboard node journal` and `syboard cloud`, with their tests, the leak scan, CI on
  Linux and macOS, and executables for macOS on Apple silicon, Linux on x86_64 and Linux on ARM.
