# Copyright 2026 The Syboard Authors
# SPDX-License-Identifier: Apache-2.0
"""The node tools on a test machine: the steps run through node.Local against a scratch folder laid out like Debian 13, with one
stub program standing in for apt-get, dpkg, systemctl, sysctl, docker, curl, ss, ip, nproc, uname, df, timedatectl, swapon,
timeout and journalctl. The stub keeps the machine's state in a file and logs every call; it never touches the network or the
Docker of the machine running the test. Usage: python tests/test_node.py (exit 0 when every check passes)."""
import calendar
import json
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
from syboard import node as N, resources  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))


STUB = r'''#!/usr/bin/env python3
import hashlib, json, os, sys
T = os.environ["FAKE_ROOT"]
S = os.path.join(T, "state.json")
prog, args = os.path.basename(sys.argv[0]), sys.argv[1:]
with open(os.path.join(T, "calls.log"), "a") as f:
    f.write(prog + " " + " ".join(args) + "\n")
st = json.load(open(S)) if os.path.exists(S) else {}
def save():
    json.dump(st, open(S, "w"))
def out(s="", code=0):
    if s:
        print(s)
    sys.exit(code)
fail = os.environ.get("FAKE_FAIL", "")
if prog == "journalctl":
    if "--list-boots" in args:
        out("IDX BOOT ID                          FIRST ENTRY                 LAST ENTRY\n"
            "  0 0f1e2d3c4b5a69788796a5b4c3d2e1f0 Sat 2026-01-31 05:00:01 UTC Sat 2026-01-31 09:00:00 UTC")
    with open(os.path.join(T, "journal_args.json"), "w") as f:
        json.dump(args, f)
    rows = ["2026-01-31T08:57:58.120000+00:00 test-node dhcpcd[400]: eth0: lease expired",
            "2026-01-31T08:58:01.000000+00:00 test-node app[901]: login secret=abcdefgh123 kept out",
            "2026-01-31T08:59:00.500000+00:00 test-node kernel: eth0: link up"]
    if "--grep" in args:
        import re as _re
        rows = [r for r in rows if _re.search(args[args.index("--grep") + 1], r)]
    out("\n".join(rows))
if prog == "uname":
    out("Linux x86_64" if "-sm" in args else "x86_64")
if prog == "nproc":
    out(os.environ.get("FAKE_CPUS", "8"))
if prog == "df":
    out("Avail\n 287G")
if prog == "timedatectl":
    out("yes")
if prog == "swapon":
    out()
if prog == "timeout":
    out(code=0 if any("/dev/tcp/" in a for a in args) else 1)
if prog == "ip":
    if "-6" in args:
        out()
    out("1: lo    inet 127.0.0.1/8 scope host lo\n2: eth0    inet 192.0.2.10/32 scope global eth0\n3: enp7s0    inet 10.1.0.5/32 scope global enp7s0")
if prog == "ss":
    lines = ["LISTEN 0 128 0.0.0.0:22 0.0.0.0:*", "LISTEN 0 128 [::]:22 [::]:*"]
    if st.get("up"):
        lines += [f"LISTEN 0 4096 127.0.0.1:{p} 0.0.0.0:*" for p in (9302, 5434, 4222, 8222, 6379)]
    if os.environ.get("FAKE_PUBLIC_LISTENER"):
        lines.append("LISTEN 0 4096 0.0.0.0:8080 0.0.0.0:*")
    out("\n".join(lines))
if prog == "sysctl":
    if "--system" in args:
        for ln in open(os.environ["SYBOARD_SYSCTL_FILE"]):
            if "=" in ln:
                k, v = ln.strip().split("=", 1)
                st[k] = v
        save()
        out()
    key = args[-1]
    out(st.get(key, {"vm.max_map_count": "65530", "vm.swappiness": "60"}.get(key, "0")))
if prog == "systemctl":
    out("systemd 257 (257.7-1)" if "--version" in args else "")
if prog == "dpkg":
    if "--print-architecture" in args:
        out("amd64")
    if "-s" in args:
        out(code=0 if args[-1] in st.get("pkgs", []) else 1)
    out()
if prog == "apt-get":
    if "install" in args:
        st.setdefault("pkgs", [])
        st["pkgs"] += [a for a in args if not a.startswith("-") and a not in ("install", "Dpkg::Options::=--force-confold")]
        save()
    out("ok")
if prog == "curl":
    url = next((a for a in args if a.startswith("http")), "")
    if url.startswith("https://") and "-w" in args:
        out("200")
    if "-o" in args and "/dev/null" not in args:
        open(args[args.index("-o") + 1], "w").write("test docker key\n")
        out()
    if url.startswith("https://"):
        out("200")
    if "127.0.0.1:9302" in url:
        out('{"status":"yellow"}' if st.get("up") else "", code=0 if st.get("up") else 7)
    if "127.0.0.1:8222/jsz" in url:
        if fail == "nojs" and st.get("up"):
            out('{"server_id": "test", "disabled": true}')
        out('{"config": {"max_memory": 1, "store_dir": "/data/jetstream"}}' if st.get("up") else "", code=0 if st.get("up") else 7)
    out(code=7)
if prog == "docker":
    if args[:1] == ["version"]:
        out("29.1.0" if "docker-ce" in st.get("pkgs", []) else "", code=0 if "docker-ce" in st.get("pkgs", []) else 1)
    if args[:1] == ["ps"]:
        out("syboard-stores-elasticsearch-1\nsyboard-stores-age-1\nsyboard-stores-nats-1\nsyboard-stores-redis-1" if st.get("up") else "")
    if args[:1] == ["compose"]:
        # as docker compose does: every --env-file must exist, and every ${VAR:?...} of the Compose file needs a value
        if "-f" in args:
            import re as _re
            vals = dict(os.environ)
            for i, a in enumerate(args):
                if a == "--env-file":
                    p = args[i + 1]
                    if not os.path.exists(p):
                        sys.stderr.write(f"env file {p} not found\n")
                        sys.exit(1)
                    for ln in open(p):
                        if "=" in ln and not ln.lstrip().startswith("#"):
                            k, v = ln.rstrip("\n").split("=", 1)
                            vals[k.strip()] = v
            text = open(args[args.index("-f") + 1]).read()
            for var, msg in _re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*):\?([^}]*)\}", text):
                if not vals.get(var):
                    sys.stderr.write(f"required variable {var} is missing a value: {msg}\n")
                    sys.exit(1)
        if "version" in args:
            out("2.40.3" if "docker-compose-plugin" in st.get("pkgs", []) else "", code=0 if "docker-compose-plugin" in st.get("pkgs", []) else 1)
        if "up" in args:
            if fail == "stores" and not st.get("failed_once"):
                st["failed_once"] = True
                save()
                out("Error: a test failure while starting the stores", 1)
            st["up"] = True
            save()
            out("started")
        if "ps" in args:
            out("\n".join(["a1", "b2", "c3", "d4"]) if st.get("up") else "")
        if "images" in args:
            out("img-" + args[-1])
        out()
    if args[:2] == ["image", "inspect"]:
        out("example/" + args[2] + "@sha256:" + hashlib.sha256(args[2].encode()).hexdigest())
    if args[:1] == ["exec"]:
        q = sys.stdin.read() if "-i" in args else args[-1]
        if "cypher(" in q:
            ok_ = st.get("graph") and fail != "nocypher"
            out("1" if ok_ else "", code=0 if ok_ else 1)
        if "create_graph" in q:
            st["graph"] = True
            save()
            out("")
        if "ag_graph" in q:
            out("1" if st.get("graph") else "0")
        out("CREATE EXTENSION")
    out()
out()
'''

PROGS = ("uname", "nproc", "df", "timedatectl", "swapon", "timeout", "ip", "ss", "sysctl", "systemctl", "dpkg", "apt-get",
         "curl", "docker", "journalctl")
MUTATING = re.compile(r"^(apt-get (update|install|-y)|systemctl enable|sysctl --system|docker compose .*\b(up|pull)\b|docker exec\b.*(create_graph|CREATE EXTENSION))")


def scratch(mem_kb=15990000):
    T = tempfile.mkdtemp(prefix="syboard-test-")
    for d in ("bin", "etc/apt/apt.conf.d", "etc/sysctl.d", "etc/apt/sources.list.d", "proc", "opt"):
        os.makedirs(os.path.join(T, d), exist_ok=True)
    with open(os.path.join(T, "etc/os-release"), "w") as f:
        f.write('ID=debian\nVERSION_ID="13"\nVERSION_CODENAME=trixie\nPRETTY_NAME="Debian GNU/Linux 13 (trixie)"\n')
    with open(os.path.join(T, "proc/meminfo"), "w") as f:
        f.write(f"MemTotal:       {mem_kb} kB\nMemFree:        14000000 kB\n")
    with open(os.path.join(T, "proc/uptime"), "w") as f:
        f.write("11000.52 80000.00\n")
    stub = os.path.join(T, "bin", "stub.py")
    with open(stub, "w") as f:
        f.write(STUB.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1))
    os.chmod(stub, 0o755)
    for p in PROGS:
        os.symlink(stub, os.path.join(T, "bin", p))
    env = dict(os.environ, FAKE_ROOT=T, PATH=os.path.join(T, "bin") + ":/usr/bin:/bin:/usr/sbin:/sbin",
               SYBOARD_NODE_DIR=os.path.join(T, "opt/syboard"), SYBOARD_SYSCTL_FILE=os.path.join(T, "etc/sysctl.d/90-syboard.conf"),
               SYBOARD_AUTO_UPGRADES=os.path.join(T, "etc/apt/apt.conf.d/20auto-upgrades"),
               SYBOARD_DOCKER_KEYRING=os.path.join(T, "etc/apt/keyrings/docker.asc"),
               SYBOARD_DOCKER_LIST=os.path.join(T, "etc/apt/sources.list.d/docker.list"),
               SYBOARD_OS_RELEASE=os.path.join(T, "etc/os-release"), SYBOARD_MEMINFO=os.path.join(T, "proc/meminfo"),
               SYBOARD_PROC_UPTIME=os.path.join(T, "proc/uptime"))
    return T, env


def calls(T):
    try:
        return [x.rstrip("\n") for x in open(os.path.join(T, "calls.log"))]
    except OSError:
        return []


def with_env(env):
    """node.py reads the target's paths from os.environ when it is called: set them for the call, put them back after."""
    keys = [k for k in env if k.startswith("SYBOARD_")]
    old = {k: os.environ.get(k) for k in keys}
    os.environ.update({k: env[k] for k in keys})
    return old


def restore(old):
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def main():
    roots = []
    try:
        # 1. the plan is read only, and it reports what the install will add and set
        T, env = scratch(); roots.append(T)
        old = with_env(env)
        p = N.plan(N.Local(env), "test-node")
        restore(old)
        st = {r["id"]: r["status"] for r in p["assessment"]}
        check("the plan assesses every requirement", len(p["assessment"]) == len(resources.REQUIREMENTS), f"{len(p['assessment'])} rows")
        check("a fresh Debian 13 machine passes, with Docker to install and the kernel settings to set",
              not p["refuse"] and st.get("os-image") == "pass" and st.get("docker") == "install" and st.get("es-map-count") == "set", json.dumps(st))
        check("a server sold with 16 GB shows about 15 GiB and still passes memory", st.get("memory") == "pass")
        check("the plan ran no command that changes the machine", not [c for c in calls(T) if MUTATING.search(c)])
        check("the plan created nothing on the machine", not os.path.exists(os.path.join(T, "opt/syboard"))
              and not os.path.exists(os.path.join(T, "etc/sysctl.d/90-syboard.conf")))
        check("every step is still to do except the listeners check, which a machine with only SSH passes",
              [s["step"] for s in p["steps"] if s["done"]] == ["listeners"], json.dumps(p["steps"]))
        # 2. a machine below a minimum is refused before any change
        T2, env2 = scratch(mem_kb=4000000); roots.append(T2)
        env2["FAKE_CPUS"] = "2"
        old = with_env(env2)
        try:
            N.apply(N.Local(env2), "test-small")
            refused = ""
        except N.NodeError as e:
            refused = str(e)
        restore(old)
        check("a machine below a minimum is refused, naming the requirements, before any change",
              "refused" in refused and "cpu" in refused and "memory" in refused and not [c for c in calls(T2) if MUTATING.search(c)], refused)
        # 3. the whole install on a fresh machine; a failure in the stores, then the resume
        T3, env3 = scratch(); roots.append(T3)
        env3["FAKE_FAIL"] = "stores"
        records = []
        old = with_env(env3)
        try:
            N.apply(N.Local(env3), "test-node", on_step=lambda n, r: records.append((n, r)))
            stopped = ""
        except N.NodeError as e:
            stopped = str(e)
        restore(old)
        check("a failure while starting the stores stops the install at that step, the earlier steps done",
              "step stores failed" in stopped and [n for n, _ in records] == ["base", "sysctl", "docker", "folders", "stores"]
              and all(r["result"] == "done" for n, r in records[:-1]) and records[-1][1]["result"] == "failed", stopped[:200])
        n_before = len(calls(T3))
        records2 = []
        old = with_env(env3)
        out = N.apply(N.Local(env3), "test-node", on_step=lambda n, r: records2.append((n, r)))
        restore(old)
        res = {n: r["result"] for n, r in records2}
        check("the next run resumes at the stores: the earlier steps are already done",
              res == {"base": "already done", "sysctl": "already done", "docker": "already done", "folders": "already done",
                      "stores": "done", "init": "done", "listeners": "already done"}, json.dumps(res))
        check("the resume installed nothing again", not [c for c in calls(T3)[n_before:] if c.startswith("apt-get")])
        compose = os.path.join(T3, "opt/syboard/stores/compose.yml")
        check("the stores' Compose file reached the node", os.path.exists(compose) and open(compose).read() == resources.STORES_COMPOSE)
        imgs = open(os.path.join(T3, "opt/syboard/stores/images.env")).read()
        check("the digests the node pulled are kept for every store",
              all(f"{s}_IMAGE=" in imgs and "@sha256:" in imgs for s in ("ES", "AGE", "NATS", "REDIS")), imgs.replace("\n", " ")[:160])
        check("the node's name reaches the stores (NATS requires it)", open(os.path.join(T3, "opt/syboard/stores/node.env")).read() == "NODE_ID=test-node\n")
        check("the secrets folder is root's only and the password is made on the machine",
              oct(os.stat(os.path.join(T3, "opt/syboard/secrets")).st_mode & 0o777) == "0o700"
              and re.match(r"^AGE_PASSWORD=[A-Za-z0-9]{32}\n$", open(os.path.join(T3, "opt/syboard/secrets/stores.env")).read() or ""))
        secret = open(os.path.join(T3, "opt/syboard/secrets/stores.env")).read().split("=", 1)[1].strip()
        blob = json.dumps(out) + json.dumps([r for _, r in records + records2]) + "".join(calls(T3))
        check("the stores' password appears in no output, record or call", secret not in blob)
        check("the init made the graph", json.load(open(os.path.join(T3, "state.json"))).get("graph") is True)
        # 4. a second run changes nothing
        n_before = len(calls(T3))
        records3 = []
        old = with_env(env3)
        N.apply(N.Local(env3), "test-node", on_step=lambda n, r: records3.append((n, r)))
        restore(old)
        check("a second run finds every step done and changes nothing",
              all(r["result"] == "already done" for _, r in records3) and not [c for c in calls(T3)[n_before:] if MUTATING.search(c)])
        # 5. the kernel settings only raise vm.max_map_count
        T5, env5 = scratch(); roots.append(T5)
        with open(os.path.join(T5, "state.json"), "w") as f:
            json.dump({"vm.max_map_count": "1048576", "vm.swappiness": "60"}, f)
        old = with_env(env5)
        N.apply(N.Local(env5), "test-node-5")
        restore(old)
        conf = open(os.path.join(T5, "etc/sysctl.d/90-syboard.conf")).read()
        check("a higher vm.max_map_count already set is kept, never lowered", "vm.max_map_count=1048576" in conf and "vm.swappiness=1" in conf)
        # 6. the init check: AGE answers a Cypher query on the graph, NATS reports JetStream on
        for flag, what in (("nojs", "NATS reports JetStream off"), ("nocypher", "AGE gives no Cypher answer")):
            envx = dict(env3, FAKE_FAIL=flag)
            old = with_env(envx)
            px = N.plan(N.Local(envx), "test-node")
            restore(old)
            check(f"the init check fails when {what}", not next(s["done"] for s in px["steps"] if s["step"] == "init"))
        # 7. a public listener other than SSH fails the last step
        env4 = dict(env3, FAKE_PUBLIC_LISTENER="1")
        old = with_env(env4)
        try:
            N.apply(N.Local(env4), "test-node")
            public = ""
        except N.NodeError as e:
            public = str(e)
        restore(old)
        check("a listener on a public address other than SSH fails the listeners step", "step listeners failed" in public, public[:120])
        # 8. the machine's own log over a window, read only
        T6, env6 = scratch(); roots.append(T6)
        old = with_env(env6)
        j = N.journal(N.Local(env6), "2026-01-31 08:50:00", "2026-01-31T09:10", lines=50)
        jargs = json.load(open(os.path.join(T6, "journal_args.json")))
        jg = N.journal(N.Local(env6), "2026-01-31 08:50:00", "2026-01-31 09:10:00", grep="dhcpcd|link up")
        jgargs = json.load(open(os.path.join(T6, "journal_args.json")))
        n6, bad = len(calls(T6)), []
        for kw in ({"since": "yesterday; reboot", "until": "2026-01-31 09:10:00"},
                   {"since": "2026-01-31 08:50", "until": "2026-01-31 09:10", "grep": "$(reboot)"},
                   {"since": "2026-01-31 08:50", "until": "2026-01-31 09:10", "lines": 5000}):
            try:
                N.journal(N.Local(env6), **kw)
                bad.append("accepted: " + json.dumps(kw))
            except N.NodeError:
                pass
        restore(old)
        gap = abs(calendar.timegm(time.strptime(j["booted_utc"], "%Y-%m-%d %H:%M:%S")) - (time.time() - 11000)) if j["booted_utc"] else 1e9
        check("the journal gives the boot time, the boots and the window's lines", gap < 120 and len(j["boots"]) == 2 and len(j["lines"]) == 3)
        check("the window goes to journalctl in UTC, one quoted value each", jargs[jargs.index("--since") + 1] == "2026-01-31 08:50:00 UTC"
              and jargs[jargs.index("--until") + 1] == "2026-01-31 09:10 UTC" and "--utc" in jargs, " ".join(jargs))
        check("a value that looks like a secret is masked", any("secret=<masked>" in x for x in j["lines"])
              and not any("abcdefgh123" in x for x in j["lines"]))
        check("--grep keeps only the matching lines", len(jg["lines"]) == 2 and "--grep" in jgargs)
        check("a window, pattern or count that is not one is refused before anything runs", not bad and len(calls(T6)) == n6, "; ".join(bad))
        check("the journal runs no command that changes the machine", not [c for c in calls(T6) if MUTATING.search(c)])
        # 9. one SSH connection carries a run's commands
        b = " ".join(N.SSH("192.0.2.10", "/nonexistent/key").base)
        check("one SSH connection carries a run's commands (multiplexing)", "ControlMaster=auto" in b and "ControlPersist=300" in b
              and "/.ssh/syboard-cm-%C" in b and len(os.path.expanduser("~/.ssh/syboard-cm-")) + 40 < 104)
    finally:
        for r in roots:
            shutil.rmtree(r, ignore_errors=True)
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
