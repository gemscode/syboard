# Copyright 2026 The Syboard Authors
# SPDX-License-Identifier: Apache-2.0
"""node verify: a node against its checklist, read only.

Part 1 installs a node on the test machine of tests/test_node.py (node.apply through node.Local and its stub programs), then verifies
it: every row passes, and the survey reads only and changes no file. Part 2 builds the survey's output for a healthy node and changes it
one fault at a time: each fault must cross its own row and level and leave every other row passing. Part 3 runs the command itself on
the same outputs, with its records in a scratch home folder. Nothing reaches the network or the Docker of the machine running the test.
Usage: python tests/test_verify.py (exit 0 when every check passes)."""
import contextlib
import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
sys.path.insert(0, HERE)
from syboard import cli, node as N, resources, verify as V  # noqa: E402
from test_node import MUTATING, calls, restore, scratch, with_env  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))


CL = resources.CHECKLIST
NODE = "test-node"
READS = re.compile(r"^(timeout \d+ )?(docker (version|ps|inspect|exec)|curl|stat|df|ss)\b")
WRITES = re.compile(r"\b(rm|mv|cp|mkdir|touch|tee|chmod|chown|ln|truncate|dd|install|apt-get|dpkg|systemctl|mktemp)\b|"
                    r"docker\s+(compose\s+)?(up|down|rm|stop|start|restart|kill|tag|build|pull|push|run|create|cp|update|network|volume|prune)\b|"
                    r"\bsysctl\s+-[wp]\b|-X\s*(POST|PUT|DELETE|PATCH)|--data|\s-T\s|\bredis-cli\b[^\n]*\b(SET|DEL|FLUSH\w*|CONFIG)\b|"
                    r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE)\b", re.I)
REDIRECT = re.compile(r"\d?>{1,2}\s*([^\s)\"';|&]+)")


def crossed(res):
    return sorted((r["module"], lv) for r in res["rows"] for lv in V.LEVELS if r["levels"][lv]["result"] == "fail")


def unknown_rows(res):
    return sorted(r["module"] for r in res["rows"] if r["row"] == "unknown")


def tree(root):
    """Every file under root with its size, mode and modification time, except the stub's own call log."""
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            if f != "calls.log":
                st = os.lstat(os.path.join(d, f))
                out[os.path.relpath(os.path.join(d, f), root)] = (st.st_size, st.st_mode, st.st_mtime_ns)
    return out


# ---- part 1: a node installed on the test machine, then verified ------------------------------------------------------------------

def part1(roots):
    T, env = scratch()
    roots.append(T)
    env["SYBOARD_SETTLE"] = "0"
    old = with_env(env)
    try:
        N.apply(N.Local(env), NODE)
        before, n0 = tree(T), len(calls(T))
        L = N.Local(env)
        res = V.run(L, NODE, CL, at="2026-01-31T09:00:00Z")
        after, made = tree(T), calls(T)[n0:]
        rows = {r["module"]: r["row"] for r in res["rows"]}
        check("a node made by node install --apply passes node verify: every module of the checklist, then the coverage row",
              res["summary"]["result"] == "pass" and list(rows) == [m["id"] for m in CL["modules"]] + ["unlisted"]
              and set(rows.values()) == {"pass"}, json.dumps(rows))
        check("the survey called only commands that read", made and all(READS.match(c) for c in made)
              and not [c for c in made if MUTATING.search(c)], repr([c for c in made if not READS.match(c)][:3]))
        check("the survey changed no file on the machine", before == after)
        check("one script went to the machine, named in the result by its sha256",
              len(L.log) == 1 and res["sent"] == [hashlib.sha256(L.log[0].encode()).hexdigest()] and res["writes_on_node"] == 0)
        secret = open(os.path.join(T, "opt/syboard/secrets/stores.env")).read().split("=", 1)[1].strip()
        check("the stores' password appears in no result or report", secret not in json.dumps(res) + "\n".join(V.report(res)))
        for flag, mod in (("nojs", "store-nats"), ("nocypher", "store-age")):
            r = V.run(N.Local(dict(env, FAKE_FAIL=flag)), NODE, CL)
            check(f"on the test machine, a fault in {mod} crosses its working level only", crossed(r) == [(mod, "working")], json.dumps(crossed(r)))
        r = V.run(N.Local(dict(env, FAKE_DISK_USE="95", FAKE_OWNER="nobody")), NODE, CL)
        check("on the test machine, a full disk crosses the machine and a secret owned by another user crosses the secrets",
              crossed(r) == [("machine", "running"), ("secrets", "present")], json.dumps(crossed(r)))
        f = os.path.join(T, "opt/syboard/secrets/stores.env")
        os.chmod(f, 0o644)
        r = V.run(N.Local(env), NODE, CL)
        os.chmod(f, 0o600)
        check("on the test machine, a secrets file others can read crosses the secrets' present level only",
              crossed(r) == [("secrets", "present")] and "stores.env 644 root" in json.dumps(r["rows"]), json.dumps(crossed(r)))
        L2 = N.Local(env)
        r = V.run(L2, "other-node", CL)
        check("a machine whose node has another name is refused: no row, no record, only the survey sent",
              "is not the node other-node" in r.get("refused", "") and f"names '{NODE}'" in r["refused"] and r["rows"] == []
              and V.records("other-node", r) == [] and len(L2.log) == 1, r.get("refused", ""))
    finally:
        restore(old)
    T2, env2 = scratch()
    roots.append(T2)
    env2["SYBOARD_SETTLE"] = "0"
    old = with_env(env2)
    try:
        r = V.run(N.Local(env2), NODE, CL)
    finally:
        restore(old)
    check("a machine that holds no node yet is refused before any check", "has no NODE_ID" in r.get("refused", "") and r["rows"] == [],
          r.get("refused", ""))


# ---- part 2: the survey's output, one fault at a time -----------------------------------------------------------------------------

STORES = {"elasticsearch": "docker.elastic.co/elasticsearch/elasticsearch:8.15.0", "age": "apache/age:release_PG16_1.5.0",
          "nats": "nats:2.10-alpine", "redis": "redis:alpine"}


def containers(over=None):
    out = {}
    for s, img in STORES.items():
        n = f"syboard-stores-{s}-1"
        out[n] = {"name": n, "image": img, "image_id": "sha256:" + hashlib.sha256(n.encode()).hexdigest(), "state": "running",
                  "started": "2026-01-31T05:00:00.000000000Z", "restarts": "0", "health": "healthy", "project": "syboard-stores", "service": s}
    for k, v in (over or {}).items():
        if v is None:
            out.pop(k, None)
        else:
            out.setdefault(k, {"name": k, "image": "example/x:1", "image_id": "sha256:x", "state": "running", "started": "t", "restarts": "0",
                               "health": "", "project": "", "service": ""}).update(v)
    return out


def line(c):
    # as docker inspect prints it: a label the container does not have is "<no value>", no health check prints nothing
    return "|".join(["/" + c["name"], c["image"], c["image_id"], c["state"], c["started"], c["restarts"], c["health"],
                     c["project"] or "<no value>", c["service"] or "<no value>"])


LISTENERS = ["0.0.0.0:22", "[::]:22", "127.0.0.53%lo:53", "127.0.0.1:9302", "127.0.0.1:5434", "127.0.0.1:4222", "127.0.0.1:8222",
             "127.0.0.1:6379"]


def survey(kv=None, c1=None, c2=None, secrets_dir=None, secrets=None, disk=None, listeners=None, end=True):
    k = {"node_id": NODE, "docker": "29.1.0", "es": '{"status":"green"}', "es_search": "200", "jetstream": "1", "redis": "PONG", "age": "1"}
    k.update(kv or {})
    c1 = c1 if c1 is not None else containers()
    c2 = c2 if c2 is not None else c1
    out = ["--- node", f"node_id={k['node_id']}", f"docker={k['docker']}"]
    out += ["--- secrets_dir"] + [f"/opt/syboard/{n} {m} {o}" for n, m, o in (secrets_dir if secrets_dir is not None else [("secrets", "700", "root")])]
    out += ["--- secrets"] + [f"/opt/syboard/secrets/{n} {m} {o}" for n, m, o in (secrets if secrets is not None else [("stores.env", "600", "root")])]
    out += ["--- disk"] + [f"{mnt} {use}" for mnt, use in (disk if disk is not None else [("/", "41%"), ("/", "41%")])]
    out += ["--- containers1"] + [line(c) for c in c1.values()]
    out += ["--- containers2"] + [line(c) for c in c2.values()]
    out += ["--- stores"] + [f"{x}={k[x]}" for x in ("es", "es_search", "jetstream", "redis", "age")]
    out += ["--- listeners"] + (listeners if listeners is not None else LISTENERS)
    return "\n".join(out + (["--- end"] if end else [])) + "\n"


class FakeT:
    """A transport that answers every script with the output given."""

    def __init__(self, out, rc=0):
        self.out, self.rc, self.log = out, rc, []

    def run(self, script, timeout=None):
        self.log.append(script)
        return self.rc, self.out


def verify(out, cl=CL, previous=None, only=None, rc=0):
    T = FakeT(out, rc)
    return V.run(T, NODE, cl, previous=previous, only=only, at="2026-01-31T09:00:00Z"), T


def refused(fn):
    try:
        fn()
        return ""
    except N.NodeError as e:
        return str(e) or "refused"


def part2():
    # the survey script reads only, and every call in it has a time limit
    script = V.survey_script("/opt/syboard", 8)
    check("the survey script holds no write command", not [ln for ln in script.splitlines() if WRITES.search(ln)])
    check("the survey script redirects output only to /dev/null", not [m.group(0) for m in REDIRECT.finditer(script) if m.group(1) != "/dev/null"])
    p = subprocess.run(["bash", "-n"], input=script, capture_output=True, text=True)
    check("bash parses the survey script (bash -n, nothing run)", p.returncode == 0, p.stderr[-200:])
    waits = []
    for ln in script.splitlines():
        for m in re.finditer(r"(?<![/\w.-])(timeout (\d+) )?(docker|curl)\s", ln):
            if (m.group(3) == "docker" and not m.group(1)) or (m.group(3) == "curl" and not re.search(r"-m \d+", ln[m.end():].split("|")[0])):
                waits.append(ln)
    check("every docker and curl call in the survey has its own time limit", not waits, repr(waits[:2]))
    caps = V.settle() + sum(int(x) for x in re.findall(r"timeout (\d+) docker", script)) + sum(int(x) for x in re.findall(r"-m (\d+)", script))
    check("the survey's time limits added up stay under the transport's timeout", caps < V.TIMEOUT, f"{caps} s of {V.TIMEOUT} s")
    check("the node's folder reaches the survey quoted", "d='/opt/my node'\n" in V.survey_script("/opt/my node", 0))
    os.environ["SYBOARD_SETTLE"] = "61"
    bad_settle = refused(V.settle)
    os.environ["SYBOARD_SETTLE"] = "x"
    bad_settle = bad_settle and refused(V.settle)
    os.environ.pop("SYBOARD_SETTLE")
    check("a settle window that is not 0 to 60 seconds is refused", bad_settle and V.settle() == 8)
    T = FakeT(survey())
    bad = [n for n in ("Node", "x;rm", "", "-x", "a" * 70, NODE + "\n") if not refused(lambda n=n: V.run(T, n, CL))]
    check("a name that is not a node's is refused before anything is sent", not bad and T.log == [], repr(bad))

    # a healthy node
    res, T = verify(survey())
    check("a healthy node: every row passes, one row per module and the coverage row",
          res["summary"]["result"] == "pass" and res["summary"]["pass"] == len(CL["modules"]) + 1 == len(res["rows"]), json.dumps(crossed(res)))
    rep = V.report(res)
    good = (rep[0].startswith(f"{NODE}: 7 of 7 rows pass; checklist node version 1 (sha256 ") and rep[0].endswith("nothing was written on the node")
            and [ln.split()[1] for ln in rep[1:]] == [r["module"] for r in res["rows"]])
    check("the report has a head line, then one line per row in the checklist's order", good, "" if good else "\n".join(rep))
    versions = {r["module"]: r["softwareVersion"] for r in res["rows"] if r["softwareVersion"]}
    check("each store's row shows its image by name and tag", versions == {"store-elasticsearch": "elasticsearch:8.15.0",
          "store-age": "age:release_PG16_1.5.0", "store-nats": "nats:2.10-alpine", "store-redis": "redis:alpine"}, json.dumps(versions))
    check("a healthy run masks nothing (no evidence reads as a secret)", "<masked>" not in json.dumps(res))
    for img, want in (("docker.elastic.co/elasticsearch/elasticsearch@sha256:0123456789abcdef0123", "elasticsearch@0123456789ab"),
                      ("nats:2.10-alpine@sha256:fedcba9876543210ffff", "nats:2.10-alpine@fedcba987654"), ("redis:alpine", "redis:alpine")):
        check(f"the image {img[:36]}... shows as {want}", V.image_version(img) == want, V.image_version(img))

    # each fault crosses its own row and level only
    es, nats, redis = "syboard-stores-elasticsearch-1", "syboard-stores-nats-1", "syboard-stores-redis-1"
    cases = [
        ("Docker does not answer", dict(kv={"docker": ""}), [("machine", "present")]),
        ("something listens on a public address", dict(listeners=LISTENERS + ["0.0.0.0:9302"]), [("machine", "running")]),
        ("the disk is 93% used", dict(disk=[("/", "93%"), ("/", "41%")]), [("machine", "running")]),
        ("the secrets folder is not root-only", dict(secrets_dir=[("secrets", "755", "root")]), [("secrets", "present")]),
        ("the node has no secrets folder", dict(secrets_dir=[], secrets=[]), [("secrets", "present")]),
        ("a secrets file the group can read", dict(secrets=[("stores.env", "640", "root")]), [("secrets", "present")]),
        ("a secrets file owned by another user", dict(secrets=[("stores.env", "600", "debian")]), [("secrets", "present")]),
        ("the stores' secrets file is missing", dict(secrets=[]), [("secrets", "present")]),
        ("Elasticsearch is red", dict(kv={"es": '{"status":"red"}'}), [("store-elasticsearch", "working")]),
        ("Elasticsearch does not answer a search", dict(kv={"es_search": "000"}), [("store-elasticsearch", "working")]),
        ("AGE does not answer the Cypher query", dict(kv={"age": ""}), [("store-age", "working")]),
        ("JetStream is off", dict(kv={"jetstream": "0"}), [("store-nats", "working")]),
        ("Redis does not answer PING", dict(kv={"redis": ""}), [("store-redis", "working")]),
        ("a store's container is missing", dict(c1=containers({redis: None})), [("store-redis", "present"), ("store-redis", "running")]),
        ("a store's container has exited", dict(c1=containers({redis: {"state": "exited"}})), [("store-redis", "running")]),
        ("a store's container is unhealthy", dict(c1=containers({nats: {"health": "unhealthy"}})), [("store-nats", "running")]),
        ("a store restarts within the settle window", dict(c2=containers({es: {"started": "2026-01-31T09:00:05Z", "restarts": "1"}})),
         [("store-elasticsearch", "running")]),
        ("a container that is on no module", dict(c1=containers({"old-job": {"state": "exited"}})), [("unlisted", "present")]),
    ]
    for label, kw, want in cases:
        r, _ = verify(survey(**kw))
        check(f"{label}: crosses {want} only", crossed(r) == sorted(want) and not unknown_rows(r) and r["summary"]["result"] == "fail",
              json.dumps(crossed(r)) + " unknown " + json.dumps(unknown_rows(r)))
    r, _ = verify(survey(disk=[]))
    check("df that gives no answer is unknown, never a pass or a cross", unknown_rows(r) == ["machine"] and crossed(r) == []
          and r["summary"]["result"] == "fail", json.dumps(unknown_rows(r)))
    r, _ = verify(survey(kv={"redis": "NOAUTH session=abcdefgh123 refused"}))
    check("evidence that reads as a secret is masked", "session=<masked>" in json.dumps(r["rows"]) and "abcdefgh123" not in json.dumps(r))
    r, _ = verify(survey(c1=containers({redis: {"state": "exited"}})))
    rep = "\n".join(V.report(r))
    good = "running containers_stable: syboard-stores-redis-1 exited" in rep and "fix: syboard node install --apply (step stores)" in rep
    check("under a crossed row the report gives the failed check, its evidence and the module's fix", good, "" if good else rep)

    # restarts: since the last verify they cross once; within the settle window they are kept as seen after it
    r, _ = verify(survey(), previous={"restarts": {nats: "0"}})
    check("no restart since the last verify: nothing crosses", crossed(r) == [])
    r, _ = verify(survey(c1=containers({nats: {"restarts": "2"}})), previous={"restarts": {nats: "0"}})
    check("a restart since the last verify crosses that store's running level",
          crossed(r) == [("store-nats", "running")] and "restarted 2 time(s) since the last verify" in json.dumps(r["rows"]), json.dumps(crossed(r)))
    r, _ = verify(survey(c2=containers({nats: {"started": "2026-01-31T09:00:05Z", "restarts": "1"}})))
    check("a restart inside the settle window is kept as seen after it, so the next run does not cross it again",
          r["summary"]["restarts"][nats] == "1")

    # a machine that does not answer, and one that is not the node
    r, _ = verify("ssh: connect to host 203.0.113.10 port 22: Connection refused\n", rc=255)
    check("a machine that does not answer is unreachable: no row judged, its summary kept as unreachable",
          not r["reachable"] and r["rows"] == [] and [x["result"] for x in V.records(NODE, r)] == ["unreachable"])
    r, _ = verify(survey(end=False), only="store-redis")
    check("a one-module run that does not reach the machine records nothing", not r["reachable"] and V.records(NODE, r) == [])
    for nid, why, label in (("other-node", "names 'other-node'", "names another node"), ("", "has no NODE_ID", "names no node")):
        r, T = verify(survey(kv={"node_id": nid}))
        check(f"a machine whose stores/node.env {label} is refused: no row, no record",
              why in r.get("refused", "") and r["rows"] == [] and V.records(NODE, r) == [] and len(T.log) == 1, r.get("refused", ""))

    # --module: that module's row alone, judged with the whole checklist's coverage; only its record
    r, _ = verify(survey(c1=containers({"old-job": {"state": "exited"}})), only="store-redis")
    recs = V.records(NODE, r)
    check("--module store-redis: one row, no coverage row (an extra container is the full run's business), only its record",
          [x["module"] for x in r["rows"]] == ["store-redis"] and r["summary"]["result"] == "pass"
          and [x["record"] for x in recs] == [f"node-verify:{NODE}:store-redis"] and "module store-redis only" in V.report(r)[0],
          json.dumps([x["record"] for x in recs]))

    # the checklist: refused when it is not one; a file of the same shape replaces the built-in one
    def with_module(**kw):
        cl = copy.deepcopy(CL)
        cl["modules"][0].update(kw)
        return cl
    dup = copy.deepcopy(CL)
    dup["modules"].append(copy.deepcopy(dup["modules"][0]))
    for label, cl, only, word in (("a check this version does not have", with_module(present=["no_such_check"]), None, "no_such_check"),
                                  ("two modules with one id", dup, None, "its own id"),
                                  ("a module with the coverage row's id", with_module(id="unlisted"), None, "its own id"),
                                  ("a cover that names nothing", with_module(covers=[{"project": "p"}]), None, "covers"),
                                  ("no modules", {"modules": []}, None, "no list of modules"),
                                  ("a module it does not hold", CL, "no-such-module", "no module no-such-module")):
        T = FakeT(survey())
        why = refused(lambda cl=cl, only=only: V.run(T, NODE, cl, only=only))
        check(f"a checklist with {label} is refused before anything is sent", word in why and T.log == [], why)
    folder = tempfile.mkdtemp(prefix="syboard-checklist-")
    try:
        mine = copy.deepcopy(CL)
        mine["id"], mine["version"] = "my-node", 3
        mine["modules"].append({"id": "my-app", "name": "my application", "covers": [{"name": "my-app"}],
                                "present": ["containers_exist"], "running": ["containers_stable"], "working": []})
        path = os.path.join(folder, "checklist.json")
        with open(path, "w") as f:
            json.dump(mine, f)
        r, _ = verify(survey(c1=containers({"my-app": {"image": "example/my-app:2.1"}})), cl=V.checklist(path))
        rows = {x["module"]: x["row"] for x in r["rows"]}
        check("--checklist FILE replaces the built-in checklist: a module for one's own container passes, and so does the coverage",
              rows.get("my-app") == "pass" and rows.get("unlisted") == "pass" and r["checklist"]["id"] == "my-node"
              and r["checklist"]["version"] == 3 and r["checklist"]["sha256"] == V.checklist_sha(mine), json.dumps(rows))
        with open(os.path.join(folder, "bad.json"), "w") as f:
            f.write("{not json")
        check("a checklist file that is not JSON, or is missing, is refused",
              "could not be read" in refused(lambda: V.checklist(os.path.join(folder, "bad.json")))
              and "could not be read" in refused(lambda: V.checklist(os.path.join(folder, "none.json"))))

        # the records, and the baseline the next run reads from them
        res, _ = verify(survey())
        recs = V.records(NODE, res)
        check("a full run gives one record per row, then the summary",
              [x["record"] for x in recs] == [f"node-verify:{NODE}:{x['module']}" for x in res["rows"]] + [f"node-verify:{NODE}"]
              and recs[-1]["result"] == "pass" and recs[-1]["writes_on_node"] == 0 and recs[-1]["sent"] == res["sent"])
        log = os.path.join(folder, "records.jsonl")
        full, _ = verify(survey(c1=containers({nats: {"restarts": "3"}})))
        down, _ = verify("no answer\n", rc=255)
        one, _ = verify(survey(c1=containers({nats: {"restarts": "9"}})), only="store-nats")
        with open(log, "w") as f:
            for x in V.records(NODE, full) + V.records(NODE, down) + V.records(NODE, one):
                f.write(json.dumps(x) + "\n")
            f.write("not a record\n")
        base = V.previous(log, NODE)
        check("the baseline is the last full run that reached the node (an unreachable run and a one-module run are not)",
              base.get("restarts", {}).get(nats) == "3", json.dumps(base)[:200])
        check("no baseline for another node or a missing file", V.previous(log, "other-node") == {}
              and V.previous(os.path.join(folder, "none.jsonl"), NODE) == {})
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    # the built-in checklist
    n_checks = sum(len(m.get(lv) or []) for m in CL["modules"] for lv in V.LEVELS)
    check("the built-in checklist holds 6 modules and 20 checks, every one known, and its not-checked list",
          len(CL["modules"]) == 6 and n_checks == 20 and not refused(lambda: V.validate(CL)) and len(CL["not_checked"]) == 2,
          f"{len(CL['modules'])} modules, {n_checks} checks")


# ---- part 3: the command ------------------------------------------------------------------------------------------------------------

def part3(roots):
    home = tempfile.mkdtemp(prefix="syboard-home-")
    roots.append(home)
    key = os.path.join(home, "test-key")
    with open(key, "w") as f:
        f.write("not a key\n")
    now = {"out": survey(), "rc": 0}
    old_home, old_ssh = os.environ.get("HOME"), N.SSH
    N.SSH = lambda host, key, user="root": FakeT(now["out"], now["rc"])
    os.environ["HOME"] = home
    log = os.path.join(home, ".syboard", "deployments", "203.0.113.10.jsonl")

    def main(*extra):
        o, e = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
            rc = cli.main(["node", "verify", "203.0.113.10", "--ssh-key", key, "--name", NODE, *extra])
        return rc, o.getvalue(), e.getvalue()

    def lines():
        with open(log) as f:
            return [json.loads(x) for x in f]
    try:
        rc, o, e = main()
        check("the command prints the report and exits 0 on a healthy node", rc == 0 and o.startswith(f"{NODE}: 7 of 7 rows pass"), o.split("\n")[0] + e)
        recs = lines()
        check("it appends one record per row and a summary to ~/.syboard/deployments/HOST.jsonl",
              len(recs) == 8 and recs[-1]["record"] == f"node-verify:{NODE}" and recs[-1]["result"] == "pass", str(len(recs)))
        now["out"] = survey(c1=containers({"syboard-stores-redis-1": {"restarts": "3"}}))
        rc, o, e = main()
        good = rc == 1 and "restarted 3 time(s) since the last verify" in o
        check("the next run reads its baseline there: a restart since crosses the row, and the command exits 1", good, "" if good else o + e)
        n = len(lines())
        rc, o, e = main("--module", "store-age", "--json")
        j = json.loads(o)
        check("--module with --json prints that module's row alone as JSON, and records only that row",
              rc == 0 and [r["module"] for r in j["rows"]] == ["store-age"] and len(lines()) == n + 1)
        now["out"] = survey(kv={"node_id": "other-node"})
        n = len(lines())
        rc, o, e = main()
        check("a machine that is not the node: exit 1, the reason on stderr, nothing recorded",
              rc == 1 and "is not the node" in e and o == "" and len(lines()) == n, e)
        now["out"], now["rc"] = "ssh: connect to host 203.0.113.10 port 22: Connection refused\n", 255
        rc, o, e = main()
        check("a machine that does not answer: exit 1, the reason on stderr, the summary recorded as unreachable",
              rc == 1 and "did not answer over SSH (exit 255)" in e and lines()[-1]["result"] == "unreachable", e)
        rc, o, e = main("--module", "no-such-module")
        check("a module the checklist does not hold is refused before the machine is reached", rc == 1 and "no module no-such-module" in e, e)
    finally:
        N.SSH = old_ssh
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home


def main():
    roots = []
    try:
        part1(roots)
        part2()
        part3(roots)
    finally:
        for r in roots:
            shutil.rmtree(r, ignore_errors=True)
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
