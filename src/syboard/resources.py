# Copyright 2026 The Syboard Authors
# SPDX-License-Identifier: Apache-2.0
"""What a node needs, the stores' Compose file and the node's checklist. All three are embedded here so that each executable is a
single file. A requirements file given with --requirements replaces REQUIREMENTS; a checklist file given with --checklist replaces
CHECKLIST."""

REQUIREMENTS = [
    {"id": "platform", "what": "Linux on the machine", "minimum": "Linux",
     "why": "the node's stores run as containers under Docker on Linux"},
    {"id": "os-image", "what": "The operating system image", "minimum": "Debian 13",
     "why": "the install steps use Debian's packages and Docker's Debian repository; one image on every node keeps them easy to maintain"},
    {"id": "cpu", "what": "Processors", "minimum": 4, "recommended": 8, "unit": "vCPU",
     "why": "Elasticsearch and the other stores share them with what runs beside them"},
    {"id": "memory", "what": "Memory", "minimum": 8, "recommended": 16, "unit": "GiB",
     "why": "Elasticsearch alone is given 2 GiB of heap and up to 6 GiB in all"},
    {"id": "disk", "what": "Free disk", "minimum": 100, "recommended": 300, "unit": "GB",
     "why": "the images, the stores' data and room to grow"},
    {"id": "arch", "what": "Processor architecture", "minimum": "x86_64 or aarch64",
     "why": "the stores' images exist for both"},
    {"id": "docker", "what": "Docker Engine and Docker Compose", "minimum": "Engine 24, Compose 2.20",
     "why": "the stores run as one Compose project; the install adds Docker when it is missing"},
    {"id": "es-map-count", "what": "vm.max_map_count", "minimum": 262144,
     "why": "Elasticsearch refuses to start below it"},
    {"id": "swap", "what": "Swap kept away from Elasticsearch", "minimum": "vm.swappiness 1 or less, or no swap",
     "why": "a swapped heap stalls Elasticsearch"},
    {"id": "host-services", "what": "systemd", "minimum": "systemd",
     "why": "Docker and the automatic security updates run as services"},
    {"id": "clock", "what": "A synchronized clock", "minimum": "NTP synchronized",
     "why": "logs and certificates need the right time"},
    {"id": "outbound", "what": "Outbound HTTPS", "minimum": "the hosts the probe lists, and port 7844",
     "why": "images, packages and model APIs are fetched over HTTPS; a Cloudflare tunnel uses port 7844"},
    {"id": "ports", "what": "Local ports free for the stores", "minimum": "4222, 8222, 9302, 5434 and 6379",
     "why": "NATS, its monitor, Elasticsearch, AGE and Redis bind to them on 127.0.0.1"},
    {"id": "private-network", "what": "An address on a private network", "minimum": "optional",
     "why": "nodes that work together talk over a private network"},
    {"id": "public-addresses", "what": "Public addresses", "minimum": "IPv4",
     "why": "some registries and services answer over IPv4 only"},
    {"id": "inbound", "what": "What faces the internet", "minimum": "only SSH",
     "why": "the stores listen on 127.0.0.1; the web reaches a node through a tunnel, not an open port"},
    {"id": "ssh-key", "what": "SSH access with a key", "minimum": "root with the node's key",
     "why": "syboard runs every command over SSH with a key"},
]

STORES_COMPOSE = """\
# The stores of a syboard node: Elasticsearch, Apache AGE, NATS with JetStream and Redis. Every port is bound to 127.0.0.1
# only and the data is kept in named volumes. `syboard node install` writes this file to <node folder>/stores/compose.yml.
# The first install pulls the images by tag and writes the digests it pulled to <node folder>/stores/images.env, so every
# later start uses the same images. Elasticsearch runs without its security layer because nothing outside the machine
# reaches it.
name: syboard-stores
services:
  elasticsearch:
    image: ${ES_IMAGE:-docker.elastic.co/elasticsearch/elasticsearch:8.15.0}
    environment:
      discovery.type: single-node
      xpack.security.enabled: "false"
      ES_JAVA_OPTS: "-Xms2g -Xmx2g"
      MALLOC_ARENA_MAX: "2"
    ports: ["127.0.0.1:9302:9200"]
    mem_limit: 6g
    volumes: ["esdata:/usr/share/elasticsearch/data"]
    healthcheck:
      test: ["CMD-SHELL", "curl -fs 'http://127.0.0.1:9200/_cluster/health?wait_for_status=yellow&timeout=5s' >/dev/null || exit 1"]
      interval: 10s
      timeout: 10s
      retries: 30
      start_period: 30s
    restart: unless-stopped
  age:
    image: ${AGE_IMAGE:-apache/age:release_PG16_1.5.0}
    command: ["postgres", "-c", "shared_preload_libraries=age"]
    environment:
      POSTGRES_USER: syboard
      POSTGRES_DB: syboard_graph
      POSTGRES_PASSWORD: ${AGE_PASSWORD:?the node's secrets file sets AGE_PASSWORD}
    ports: ["127.0.0.1:5434:5432"]
    volumes: ["agedata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U syboard -d syboard_graph"]
      interval: 5s
      timeout: 5s
      retries: 30
    restart: unless-stopped
  nats:
    image: ${NATS_IMAGE:-nats:2.10-alpine}
    command: ["-js", "-sd", "/data", "-m", "8222", "-n", "${NODE_ID:?the node id}"]
    ports: ["127.0.0.1:4222:4222", "127.0.0.1:8222:8222"]
    volumes: ["natsdata:/data"]
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1:8222/healthz >/dev/null 2>&1 || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 30
    restart: unless-stopped
  redis:
    image: ${REDIS_IMAGE:-redis:alpine}
    command: ["redis-server", "--appendonly", "yes"]
    ports: ["127.0.0.1:6379:6379"]
    volumes: ["redisdata:/data"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 30
    restart: unless-stopped
volumes:
  esdata: {}
  agedata: {}
  natsdata: {}
  redisdata: {}
"""

# The node's checklist: every module a node installed by `syboard node install` holds, each a schema.org SoftwareApplication with
# the checks of its three levels (`syboard node verify` names a check by its id; syboard.verify.CHECKS holds them). A module covers
# the containers it names by Compose project and service, or by container name. A checklist file given with --checklist has the same
# shape, so a node that runs more can list its own modules.
CHECKLIST = {
    "@type": "ItemList",
    "id": "node",
    "version": 1,
    "for": "a node installed by syboard node install",
    "levels": {
        "present": "its containers exist and its files are in place",
        "running": "its containers are up and healthy, unchanged over the settle window and not restarted since the last verify",
        "working": "a real read that a person's use of the module depends on passes",
    },
    "modules": [
        {"id": "machine", "@type": "SoftwareApplication", "name": "the machine and Docker", "covers": [],
         "present": ["docker_answers"], "running": ["only_ssh_public", "disk_space"], "working": [],
         "fix": "syboard node install --apply (steps base, sysctl, docker)"},
        {"id": "secrets", "@type": "SoftwareApplication", "name": "the node's secrets: names, modes and owner only, no value read",
         "covers": [], "secrets": ["stores.env"], "present": ["secrets_root_only"], "running": [], "working": [],
         "fix": "syboard node install --apply (step folders)"},
        {"id": "store-elasticsearch", "@type": "SoftwareApplication", "name": "Elasticsearch 8.15.0",
         "covers": [{"project": "syboard-stores", "service": "elasticsearch"}],
         "present": ["containers_exist"], "running": ["containers_stable", "containers_healthy"], "working": ["es_health"],
         "fix": "syboard node install --apply (steps stores, init)"},
        {"id": "store-age", "@type": "SoftwareApplication", "name": "Apache AGE (PostgreSQL 16)",
         "covers": [{"project": "syboard-stores", "service": "age"}],
         "present": ["containers_exist"], "running": ["containers_stable", "containers_healthy"], "working": ["age_cypher"],
         "fix": "syboard node install --apply (steps stores, init)"},
        {"id": "store-nats", "@type": "SoftwareApplication", "name": "NATS 2.10 with JetStream",
         "covers": [{"project": "syboard-stores", "service": "nats"}],
         "present": ["containers_exist"], "running": ["containers_stable", "containers_healthy"], "working": ["nats_jetstream"],
         "fix": "syboard node install --apply (steps stores, init)"},
        {"id": "store-redis", "@type": "SoftwareApplication", "name": "Redis",
         "covers": [{"project": "syboard-stores", "service": "redis"}],
         "present": ["containers_exist"], "running": ["containers_stable", "containers_healthy"], "working": ["redis_ping"],
         "fix": "syboard node install --apply (step stores)"},
    ],
    "not_checked": [
        {"what": "a write through each store (an index, a graph vertex, a stream message, a key)",
         "why": "node verify reads only and writes nothing on the node"},
        {"what": "the kernel settings, the automatic security updates and the other install steps",
         "why": "syboard node plan runs each install step's own check"},
    ],
}
