# Copyright 2026 The Syboard Authors
# SPDX-License-Identifier: Apache-2.0
"""A node's machine over SSH: its assessment against the requirements, the install of its stores, and its own log.

plan() runs read-only commands and returns the assessment and the steps still to do; it changes nothing. apply() refuses a
machine below any minimum, then runs each step whose check does not pass yet, so a second run changes nothing and a run
stopped in a step resumes at that step. Every command goes to the machine as a script on the standard input of `bash -s`,
so nothing is quoted on a command line, and one SSH connection carries every command of a run.

No secret is printed or brought back: the stores' password is made on the node, in a file only root reads, and Compose
reads it there.

The tests run the same steps through the Local transport against a scratch folder with stub programs; the target's paths
come from tcfg(), which the tests point into their scratch folder through SYBOARD_* variables."""
import json
import os
import re
import shlex
import subprocess
import time

from . import resources

STEPS = ("base", "sysctl", "docker", "folders", "stores", "init", "listeners")
NODE_PORTS = (4222, 8222, 9302, 5434, 6379)
OUTBOUND = ("api.anthropic.com", "registry-1.docker.io", "docker.elastic.co", "ghcr.io", "download.docker.com", "github.com")
GRAPH = "syboard"


class NodeError(Exception):
    """A refusal or a failed step; what was done before it is in the message."""


def tcfg():
    """The machine's paths; the tests point them into a scratch folder."""
    def e(name, default):
        return os.environ.get("SYBOARD_" + name, default)
    return {"home": e("NODE_DIR", "/opt/syboard"), "sysctl": e("SYSCTL_FILE", "/etc/sysctl.d/90-syboard.conf"),
            "auto": e("AUTO_UPGRADES", "/etc/apt/apt.conf.d/20auto-upgrades"), "keyring": e("DOCKER_KEYRING", "/etc/apt/keyrings/docker.asc"),
            "docker_list": e("DOCKER_LIST", "/etc/apt/sources.list.d/docker.list"), "os_release": e("OS_RELEASE", "/etc/os-release"),
            "meminfo": e("MEMINFO", "/proc/meminfo"), "uptime": e("PROC_UPTIME", "/proc/uptime")}


# ---- transports -----------------------------------------------------------------------------------------------------------

class SSH:
    """The machine over SSH with a key. One connection carries every command and upload of a run (OpenSSH multiplexing)."""

    def __init__(self, host, key, user="root"):
        self.base = ["ssh", "-i", key, "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=accept-new",
                     "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30", "-o", "ControlMaster=auto",
                     "-o", "ControlPath=" + os.path.expanduser("~/.ssh/syboard-cm-%C"), "-o", "ControlPersist=300", f"{user}@{host}"]
        self.log = []

    def run(self, script, timeout=1800):
        self.log.append(script)
        try:
            p = subprocess.run(self.base + ["bash", "-s"], input=script, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, f"timed out after {timeout} s"
        return p.returncode, (p.stdout + p.stderr)

    def put(self, data, remote, timeout=600):
        """Writes bytes to a file on the machine, readable by root only."""
        self.log.append(f"put {remote}")
        p = subprocess.run(self.base + [f"umask 077; mkdir -p {shlex.quote(os.path.dirname(remote))} && cat > {shlex.quote(remote)}"],
                           input=data, capture_output=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")


class Local:
    """The test machine: the same scripts, run here with the test's environment (its stub programs and scratch paths)."""

    def __init__(self, env):
        self.env, self.log = env, []

    def run(self, script, timeout=300):
        self.log.append(script)
        p = subprocess.run(["bash", "-s"], input=script, capture_output=True, text=True, timeout=timeout, env=self.env)
        return p.returncode, (p.stdout + p.stderr)

    def put(self, data, remote, timeout=60):
        self.log.append(f"put {remote}")
        os.makedirs(os.path.dirname(remote), exist_ok=True)
        with open(remote, "wb") as f:
            f.write(data)
        return 0, ""


# ---- the requirements and the assessment --------------------------------------------------------------------------------------

def requirements(path=None):
    """-> {id: requirement}: the embedded requirements, or a JSON file of the same shape (a list, or {"requirements": [...]})."""
    rows = resources.REQUIREMENTS
    if path:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        rows = data["requirements"] if isinstance(data, dict) else data
    return {r["id"]: r for r in rows}


def probe_script(c):
    hosts = " ".join(OUTBOUND)
    return f"""set +e
echo "os=$(. {c['os_release']} 2>/dev/null && echo "$ID $VERSION_ID")"
echo "kernel=$(uname -sm)"
echo "arch=$(uname -m)"
echo "cpus=$(nproc 2>/dev/null)"
echo "mem_kb=$(awk '/MemTotal/ {{print $2}}' {c['meminfo']} 2>/dev/null)"
echo "disk_avail_gb=$(df -BG --output=avail / 2>/dev/null | tail -1 | tr -dc 0-9)"
echo "docker=$(docker version -f '{{{{.Server.Version}}}}' 2>/dev/null || echo none)"
echo "compose=$(docker compose version --short 2>/dev/null || echo none)"
echo "map_count=$(sysctl -n vm.max_map_count 2>/dev/null)"
echo "swappiness=$(sysctl -n vm.swappiness 2>/dev/null)"
echo "swap_devices=$(swapon --show --noheadings 2>/dev/null | wc -l | tr -dc 0-9)"
echo "systemd=$(systemctl --version 2>/dev/null | head -1)"
echo "ntp=$(timedatectl show -p NTPSynchronized --value 2>/dev/null)"
echo "private=$(ip -4 -o addr show 2>/dev/null | awk '{{print $4}}' | grep -E '^10\\.' | head -1)"
echo "ipv6_global=$(ip -6 -o addr show scope global 2>/dev/null | wc -l | tr -dc 0-9)"
echo "listeners=$(ss -ltnH 2>/dev/null | awk '{{print $4}}' | tr '\\n' ' ')"
echo "containers=$(docker ps --format '{{{{.Names}}}}' 2>/dev/null | tr '\\n' ' ')"
for h in {hosts}; do
  if command -v curl >/dev/null 2>&1; then code=$(curl -4 -s -o /dev/null -m 10 -w '%{{http_code}}' "https://$h/"); else
    timeout 6 bash -c "</dev/tcp/$h/443" 2>/dev/null && code=tcp || code=000; fi
  echo "https_$h=$code"
done
echo "tunnel_7844=$(timeout 6 bash -c '</dev/tcp/region1.v2.argotunnel.com/7844' 2>/dev/null && echo open || echo closed)"
"""


def parse(out):
    return {k: v.strip() for k, v in (ln.split("=", 1) for ln in out.splitlines() if "=" in ln and re.match(r"^[a-z0-9_.-]+=", ln))}


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def assess(m, reqs):
    """-> rows (id, what, minimum, recommended, measured, status, note); status is pass, warn, fail, install (the install adds it)
    or set (the install sets it)."""
    rows = []

    def row(rid, measured, status, note=""):
        r = reqs.get(rid, {})
        rows.append({"id": rid, "what": r.get("what", rid), "minimum": r.get("minimum"), "recommended": r.get("recommended"),
                     "measured": measured, "status": status, "note": note})

    def scale(rid, value, slack=1.0, unit=""):
        r = reqs.get(rid, {})
        lo, hi = _num(r.get("minimum")), _num(r.get("recommended"))
        if value is None:
            return row(rid, "unknown", "fail", "the machine did not answer")
        status = "fail" if lo is not None and value < lo * slack else "warn" if hi is not None and value < hi * slack else "pass"
        note = "" if slack == 1.0 else f"a server sold with {int(hi or 0)} {unit} shows about {int(round((hi or 0) * 0.95))} {unit}"
        row(rid, f"{value:g} {unit}".strip(), status, note)
    linux = "Linux" in m.get("kernel", "")
    row("platform", f"{m.get('kernel', '')} {m.get('os', '')}".strip(), "pass" if linux else "fail")
    row("os-image", m.get("os", "unknown"), "pass" if m.get("os") == "debian 13" else "fail")
    scale("cpu", _num(m.get("cpus")), unit="vCPU")
    mem = _num(m.get("mem_kb"))
    scale("memory", round(mem / 1024 / 1024, 1) if mem else None, slack=0.9, unit="GiB")
    scale("disk", _num(m.get("disk_avail_gb")), unit="GB free")
    row("arch", m.get("arch", "unknown"), "pass" if m.get("arch") in ("x86_64", "aarch64") else "fail")
    dv, cv = m.get("docker", "none"), m.get("compose", "none")
    if dv == "none":
        row("docker", "not installed", "install")
    else:
        ok = (_num(dv.split(".")[0]) or 0) >= 24 and [int(x) for x in re.findall(r"\d+", cv)[:2]] >= [2, 20]
        row("docker", f"Engine {dv}, Compose {cv}", "pass" if ok else "fail")
    mc = _num(m.get("map_count"))
    row("es-map-count", m.get("map_count", "unknown"), "pass" if mc and mc >= 262144 else "set")
    sw, swd = _num(m.get("swappiness")), _num(m.get("swap_devices"))
    row("swap", f"swappiness {m.get('swappiness')}, swap devices {m.get('swap_devices')}",
        "pass" if (sw is not None and sw <= 1) or swd == 0 else "set")
    row("host-services", m.get("systemd", "") or "none", "pass" if m.get("systemd", "").startswith("systemd") else "fail")
    row("clock", f"NTP synchronized: {m.get('ntp')}", "pass" if m.get("ntp") == "yes" else "warn")
    bad = [h for h in OUTBOUND if m.get(f"https_{h}", "000") in ("000", "")]
    t7844 = m.get("tunnel_7844")
    row("outbound", "all reachable" if not bad and t7844 == "open" else f"unreachable: {', '.join(bad + ([] if t7844 == 'open' else ['7844']))}",
        "pass" if not bad and t7844 == "open" else "fail")
    ours = "syboard-stores" in m.get("containers", "")
    held = [p for p in NODE_PORTS if re.search(rf"[:.]{p}(\s|$)", m.get("listeners", "") + " ")]
    row("ports", "free" if not held else f"in use: {', '.join(map(str, held))}", "pass" if not held or ours else "fail",
        "held by the node's own stores" if held and ours else "")
    row("private-network", m.get("private") or "none", "pass" if m.get("private") else "warn",
        "" if m.get("private") else "no address on a private network: the node runs alone")
    v6 = _num(m.get("ipv6_global"))
    row("public-addresses", f"IPv6 global addresses: {m.get('ipv6_global')}; GitHub over IPv4: {m.get('https_github.com')}",
        "pass" if v6 == 0 and m.get("https_github.com", "000") not in ("000", "") else "warn")
    public = [a for a in m.get("listeners", "").split() if not re.match(r"^(127\.|\[::1\]|::1)", a) and not re.search(r"[:.]22$", a)]
    row("inbound", "only SSH faces the internet" if not public else f"also listening: {' '.join(public)}", "pass" if not public else "warn")
    row("ssh-key", "signed in with the node's key", "pass")
    return rows


# ---- the steps --------------------------------------------------------------------------------------------------------------

def step_scripts(c, node):
    d = c["home"]
    stores = f"{d}/stores"
    # every Compose command reads node.env, which holds NODE_ID (the NATS server's name, required by the Compose file)
    compose = (f"docker compose --env-file {d}/secrets/stores.env --env-file {stores}/images.env --env-file {stores}/node.env "
               f"-p syboard-stores -f {stores}/compose.yml")
    return {
        "base": (
            f"dpkg -s unattended-upgrades >/dev/null 2>&1 && grep -q 'Unattended-Upgrade \"1\"' {c['auto']}",
            f"""set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get -y -q -o Dpkg::Options::=--force-confold upgrade
apt-get -y -q install ca-certificates curl unattended-upgrades jq
printf 'APT::Periodic::Update-Package-Lists "1";\\nAPT::Periodic::Unattended-Upgrade "1";\\n' > {c['auto']}
systemctl enable --now unattended-upgrades
[ -f /var/run/reboot-required ] && echo "reboot-required: a kernel update waits for the next restart" || true
"""),
        "sysctl": (
            f"[ \"$(sysctl -n vm.max_map_count)\" -ge 262144 ] && [ \"$(sysctl -n vm.swappiness)\" -le 1 ] && grep -q max_map_count {c['sysctl']}",
            f"""set -e
mc=$(sysctl -n vm.max_map_count)
[ "$mc" -ge 262144 ] 2>/dev/null || mc=262144
printf 'vm.max_map_count=%s\\nvm.swappiness=1\\n' "$mc" > {c['sysctl']}
sysctl --system >/dev/null
echo "vm.max_map_count=$(sysctl -n vm.max_map_count) vm.swappiness=$(sysctl -n vm.swappiness)"
"""),
        "docker": (
            "docker version -f '{{.Server.Version}}' >/dev/null 2>&1 && docker compose version --short >/dev/null 2>&1",
            f"""set -e
export DEBIAN_FRONTEND=noninteractive
install -m 0755 -d "$(dirname {c['keyring']})"
curl -fsSL https://download.docker.com/linux/debian/gpg -o {c['keyring']}
chmod a+r {c['keyring']}
. {c['os_release']}
echo "deb [arch=$(dpkg --print-architecture) signed-by={c['keyring']}] https://download.docker.com/linux/debian $VERSION_CODENAME stable" > {c['docker_list']}
apt-get update -q
apt-get -y -q install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
echo "docker=$(docker version -f '{{{{.Server.Version}}}}') compose=$(docker compose version --short)"
"""),
        "folders": (
            f"[ -d {stores} ] && ls -ld {d}/secrets | grep -q '^drwx------'",
            f"""set -e
install -d -m 0755 {d} {stores}
install -d -m 0700 {d}/secrets
umask 077
[ -s {d}/secrets/stores.env ] || printf 'AGE_PASSWORD=%s\\n' "$(head -c 48 /dev/urandom | base64 | tr -dc A-Za-z0-9 | head -c 32)" > {d}/secrets/stores.env
echo "folders ready"
"""),
        "stores": (
            f"[ -f {stores}/compose.yml ] && [ \"$({compose} ps --status running -q 2>/dev/null | wc -l | tr -dc 0-9)\" = 4 ] && "
            f"curl -fs 'http://127.0.0.1:9302/_cluster/health?wait_for_status=yellow&timeout=5s' >/dev/null",
            f"""set -e
touch {stores}/images.env
printf 'NODE_ID=%s\\n' {shlex.quote(node)} > {stores}/node.env
{compose} pull -q
{compose} up -d --wait
for s in elasticsearch age nats redis; do
  img=$({compose} images -q "$s" | head -1)
  dig=$(docker image inspect "$img" --format '{{{{index .RepoDigests 0}}}}')
  echo "$(echo "$s" | tr a-z A-Z | sed 's/ELASTICSEARCH/ES/')_IMAGE=$dig"
done > {stores}/images.env
cat {stores}/images.env
"""),
        "init": (
            # Elasticsearch answers yellow or green, AGE answers a Cypher query on the node's graph, NATS reports JetStream on
            "curl -fs 'http://127.0.0.1:9302/_cluster/health?wait_for_status=yellow&timeout=5s' >/dev/null && "
            "[ \"$(docker exec -i syboard-stores-age-1 psql -U syboard -d syboard_graph -tAq 2>/dev/null <<'SQL'\n"
            "LOAD 'age';\nSET search_path = ag_catalog, \"$user\", public;\n"
            f"SELECT * FROM cypher('{GRAPH}', $$ RETURN 1 $$) AS (x agtype);\nSQL\n"
            ")\" = 1 ] && "
            "curl -fs http://127.0.0.1:8222/jsz | grep -q '\"store_dir\": *\"/data'",
            f"""set -e
docker exec syboard-stores-age-1 psql -U syboard -d syboard_graph -v ON_ERROR_STOP=1 -tAc "CREATE EXTENSION IF NOT EXISTS age"
n=$(docker exec syboard-stores-age-1 psql -U syboard -d syboard_graph -tAc "LOAD 'age'; SELECT count(*) FROM ag_catalog.ag_graph WHERE name='{GRAPH}'" | tail -1)
[ "$n" = 1 ] || docker exec syboard-stores-age-1 psql -U syboard -d syboard_graph -v ON_ERROR_STOP=1 -tAc "LOAD 'age'; SET search_path = ag_catalog, public; SELECT create_graph('{GRAPH}')"
echo "graph={GRAPH} jetstream=$(curl -fs http://127.0.0.1:8222/jsz | grep -c '\"config\"')"
"""),
        "listeners": (
            "! ss -ltnH | awk '{print $4}' | grep -vE '^(127\\.|\\[::1\\]|::1)' | grep -vE '[:.]22$' | grep -q .",
            None),                                    # nothing to change: a public listener other than SSH is reported
    }


TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")
GREP_RE = re.compile(r"^[A-Za-z0-9 _.:/|()-]{1,80}$")
SECRET_LIKE = re.compile(r"(?i)(token|secret|cookie|session|password|passwd|authorization|api[_-]?key)([=:\"' ]+)[^\s\"'&,;]{6,}")


def journal(T, since, until, grep=None, lines=200):
    """The machine's own log over a window, read only: its boot time, its last boots, and the journal's lines from since to until
    in UTC (the newest `lines` of them, only those matching grep when it is given), with values that look like secrets masked.
    The window and the pattern are checked before anything runs and go to the machine quoted."""
    for name, v in (("since", since), ("until", until)):
        if not (v and TIME_RE.match(v.strip())):
            raise NodeError(f"--{name} is a UTC time such as 2026-01-31 08:30:00 (given: {v!r})")
    if grep is not None and not GREP_RE.match(grep):
        raise NodeError("--grep is 1 to 80 letters, digits, spaces and _ . : / | ( ) -")
    lines = int(lines)
    if not 1 <= lines <= 2000:
        raise NodeError("--lines is 1 to 2000")
    c = tcfg()
    s, u = since.strip().replace("T", " "), until.strip().replace("T", " ")
    g = f" --grep {shlex.quote(grep)}" if grep else ""
    rc, out = T.run(f"""set +e
echo "now_epoch=$(date -u +%s)"
echo "uptime_s=$(cut -d. -f1 {shlex.quote(c['uptime'])} 2>/dev/null)"
echo "--- boots"
journalctl --list-boots --no-pager 2>&1 | tail -5
echo "--- journal"
journalctl --no-pager --utc -o short-iso-precise --since {shlex.quote(s + ' UTC')} --until {shlex.quote(u + ' UTC')}{g} 2>&1 | tail -n {lines}
""", timeout=120)
    if "--- journal" not in out:
        raise NodeError(f"the machine did not answer over SSH (exit {rc}): {out[-300:]}")
    head, rest = out.split("--- boots", 1)
    boots, body = rest.split("--- journal", 1)
    f = parse(head)
    try:
        up = int(f.get("uptime_s") or "")
        booted = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(int(f["now_epoch"]) - up))
        uptime = f"{up // 3600} h {up % 3600 // 60} min"
    except (KeyError, ValueError):
        booted, uptime = None, None

    def masked(xs):
        return [SECRET_LIKE.sub(r"\1\2<masked>", x)[:400] for x in xs if x.strip()]
    return {"booted_utc": booted, "uptime": uptime, "boots": masked(boots.splitlines()),
            "window": f"{s} UTC to {u} UTC" + (f", lines matching {grep}" if grep else ""), "lines": masked(body.splitlines())}


def plan(T, node, reqs_path=None):
    """The assessment and the steps still to do; read only."""
    c = tcfg()
    reqs = requirements(reqs_path)
    rc, out = T.run(probe_script(c), timeout=180)
    if rc and not out:
        raise NodeError(f"the machine did not answer over SSH (exit {rc})")
    rows = assess(parse(out), reqs)
    todo = []
    for name in STEPS:
        rc, _ = T.run(step_scripts(c, node)[name][0], timeout=60)
        todo.append({"step": name, "done": rc == 0})
    return {"node": node, "assessment": rows, "refuse": [r["id"] for r in rows if r["status"] == "fail"], "steps": todo}


def apply(T, node, on_step=None, reqs_path=None):
    """Every step whose check does not pass, in order; refuses below any minimum first. on_step(name, result) records each step."""
    p = plan(T, node, reqs_path)
    if p["refuse"]:
        raise NodeError(f"refused: below the minimum for {', '.join(p['refuse'])}; nothing was changed")
    c = tcfg()
    scripts = step_scripts(c, node)
    done = []
    for name in STEPS:
        check, do = scripts[name]
        rc, _ = T.run(check, timeout=60)
        if rc == 0:
            res = {"step": name, "result": "already done"}
        elif do is None:
            res = {"step": name, "result": "failed", "out": "the check did not pass and the step has nothing to change"}
        else:
            if name == "stores":
                rc, out = T.put(resources.STORES_COMPOSE.encode(), f"{c['home']}/stores/compose.yml")
                if rc:
                    raise NodeError(f"step stores: the Compose file did not reach the machine: {out[-300:]}")
            rc, out = T.run(do, timeout=1800)
            res = {"step": name, "result": "done" if rc == 0 else "failed", "out": out[-600:]}
        if res["result"] != "failed":
            rc, _ = T.run(check, timeout=120)
            if rc:
                res = dict(res, result="failed", out=(res.get("out", "") + "\nthe step's check still does not pass")[-600:])
        done.append(res)
        if on_step:
            on_step(name, res)
        if res["result"] == "failed":
            raise NodeError(f"step {name} failed: {res.get('out', '')[-400:]}; earlier steps: "
                            + ", ".join(f"{x['step']} {x['result']}" for x in done[:-1]))
    return dict(p, applied=True, done=done)
