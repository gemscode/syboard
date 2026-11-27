---
version: 0.2.0
---

# Node requirements and checklist

Version 0.2.0 · Generated from `src/syboard/resources.py` by `scripts/gen_docs_reference.py`.

## Requirements

`syboard node plan` measures a machine against these requirements, and `syboard node install` refuses a machine below any minimum. A JSON file of the same shape replaces them with `--requirements`.

| Requirement | Minimum | Recommended | Why |
|---|---|---|---|
| Linux on the machine (`platform`) | Linux |  | the node's stores run as containers under Docker on Linux |
| The operating system image (`os-image`) | Debian 13 |  | the install steps use Debian's packages and Docker's Debian repository; one image on every node keeps them easy to maintain |
| Processors (`cpu`) | 4 vCPU | 8 vCPU | Elasticsearch and the other stores share them with what runs beside them |
| Memory (`memory`) | 8 GiB | 16 GiB | Elasticsearch alone is given 2 GiB of heap and up to 6 GiB in all |
| Free disk (`disk`) | 100 GB | 300 GB | the images, the stores' data and room to grow |
| Processor architecture (`arch`) | x86_64 or aarch64 |  | the stores' images exist for both |
| Docker Engine and Docker Compose (`docker`) | Engine 24, Compose 2.20 |  | the stores run as one Compose project; the install adds Docker when it is missing |
| vm.max_map_count (`es-map-count`) | 262144 |  | Elasticsearch refuses to start below it |
| Swap kept away from Elasticsearch (`swap`) | vm.swappiness 1 or less, or no swap |  | a swapped heap stalls Elasticsearch |
| systemd (`host-services`) | systemd |  | Docker and the automatic security updates run as services |
| A synchronized clock (`clock`) | NTP synchronized |  | logs and certificates need the right time |
| Outbound HTTPS (`outbound`) | the hosts the probe lists, and port 7844 |  | images, packages and model APIs are fetched over HTTPS; a Cloudflare tunnel uses port 7844 |
| Local ports free for the stores (`ports`) | 4222, 8222, 9302, 5434 and 6379 |  | NATS, its monitor, Elasticsearch, AGE and Redis bind to them on 127.0.0.1 |
| An address on a private network (`private-network`) | optional |  | nodes that work together talk over a private network |
| Public addresses (`public-addresses`) | IPv4 |  | some registries and services answer over IPv4 only |
| What faces the internet (`inbound`) | only SSH |  | the stores listen on 127.0.0.1; the web reaches a node through a tunnel, not an open port |
| SSH access with a key (`ssh-key`) | root with the node's key |  | syboard runs every command over SSH with a key |

## Checklist

`syboard node verify` checks each module of the checklist (version 1) at three levels. A JSON file of the same shape replaces it with `--checklist`.

| Level | What passes |
|---|---|
| present | its containers exist and its files are in place |
| running | its containers are up and healthy, unchanged over the settle window and not restarted since the last verify |
| working | a real read that a person's use of the module depends on passes |

| Module | What it is | Present | Running | Working | Fix when it fails |
|---|---|---|---|---|---|
| `machine` | the machine and Docker | `docker_answers` | `only_ssh_public`, `disk_space` |  | syboard node install --apply (steps base, sysctl, docker) |
| `secrets` | the node's secrets: names, modes and owner only, no value read | `secrets_root_only` |  |  | syboard node install --apply (step folders) |
| `store-elasticsearch` | Elasticsearch 8.15.0 | `containers_exist` | `containers_stable`, `containers_healthy` | `es_health` | syboard node install --apply (steps stores, init) |
| `store-age` | Apache AGE (PostgreSQL 16) | `containers_exist` | `containers_stable`, `containers_healthy` | `age_cypher` | syboard node install --apply (steps stores, init) |
| `store-nats` | NATS 2.10 with JetStream | `containers_exist` | `containers_stable`, `containers_healthy` | `nats_jetstream` | syboard node install --apply (steps stores, init) |
| `store-redis` | Redis | `containers_exist` | `containers_stable`, `containers_healthy` | `redis_ping` | syboard node install --apply (step stores) |

One more row, `coverage`, checks that every container on the machine belongs to a module.

### Not checked

| What | Why |
|---|---|
| a write through each store (an index, a graph vertex, a stream message, a key) | node verify reads only and writes nothing on the node |
| the kernel settings, the automatic security updates and the other install steps | syboard node plan runs each install step's own check |
