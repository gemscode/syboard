# Copyright 2026 The Syboard Authors
# SPDX-License-Identifier: Apache-2.0
"""A node against its checklist, read only.

The checklist (resources.CHECKLIST, or a JSON file of the same shape) lists every module a node holds. Each module is a schema.org
SoftwareApplication with three levels of checks: present (its containers exist and its files are in place), running (its containers
are up and healthy, unchanged over the settle window and not restarted since the last verify) and working (a real read that a person's
use of the module depends on). Each check is one small function of the facts below, so one fault crosses one row at one level. One more
row checks that every container on the machine belongs to a module.

The facts come from one survey script sent over the transport. It only reads: the node's name in stores/node.env, the names, modes
and owner of the secrets (never a value), df, docker ps and inspect, read-only queries inside the stores, GETs on 127.0.0.1 and ss.
Its only parameters are the node's folder and the settle window, so nothing given on the command line reaches the machine, and
nothing is written there. A machine whose stores/node.env does not name the node is refused before any check. The result names every
script sent by its sha256.

records() turns a result into one record per module and, for a full run, a summary; the command appends them to
~/.syboard/deployments/<host>.jsonl beside node install's step records, and previous() reads the last full run's restart counts there."""
import hashlib
import json
import os
import re
import shlex

from . import node, resources

LEVELS = ("present", "running", "working")
TIMEOUT = 240            # above the survey's own time limits added up (about 150 s); a normal run takes seconds
DISK_MAX = 90            # per cent: below Elasticsearch's 95 % flood stage, which makes every index read-only
NODE_RE = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")          # used with fullmatch: no trailing newline gets through
ROOT_ONLY = re.compile(r"^[0-7]?[0-7]00$")                            # 600, 400, a 700 folder: nothing for the group or others
KEY_LIKE = re.compile(r"\b(sk-ant-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_=-]{20,}(?:\.[A-Za-z0-9_=-]+){0,2})")
FMT = ('{{.Name}}|{{.Config.Image}}|{{.Image}}|{{.State.Status}}|{{.State.StartedAt}}|{{.RestartCount}}|'
       '{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{index .Config.Labels "com.docker.compose.project"}}|'
       '{{index .Config.Labels "com.docker.compose.service"}}')

# The one survey script. @@D@@ (the node's folder, quoted), @@SETTLE@@ (seconds), @@FMT@@ and @@GRAPH@@ are its only parameters.
# Every call that could wait has its own limit (timeout or curl -m), and their sum stays under TIMEOUT.
SURVEY = r"""set +e
d=@@D@@
echo "--- node"
echo "node_id=$(sed -n 's/^NODE_ID=//p' "$d/stores/node.env" 2>/dev/null | head -1)"
echo "docker=$(timeout 10 docker version --format '{{.Server.Version}}' 2>/dev/null)"
echo "--- secrets_dir"
[ -e "$d/secrets" ] && stat -c '%n %a %U' "$d/secrets"
echo "--- secrets"
for f in "$d"/secrets/*; do [ -e "$f" ] && stat -c '%n %a %U' "$f"; done
echo "--- disk"
df -P "$d" /var/lib/docker 2>/dev/null | tail -n +2 | awk '{print $6, $5}'
echo "--- containers1"
timeout 20 docker ps -aq | xargs -r timeout 20 docker inspect -f '@@FMT@@' 2>/dev/null
sleep @@SETTLE@@
echo "--- containers2"
timeout 20 docker ps -aq | xargs -r timeout 20 docker inspect -f '@@FMT@@' 2>/dev/null
echo "--- stores"
echo "es=$(curl -s -m 10 'http://127.0.0.1:9302/_cluster/health?filter_path=status')"
echo "es_search=$(curl -s -o /dev/null -m 10 -w '%{http_code}' 'http://127.0.0.1:9302/_search?size=0')"
echo "jetstream=$(curl -fs -m 10 http://127.0.0.1:8222/jsz | grep -c '"store_dir": *"/data')"
echo "redis=$(timeout 10 docker exec syboard-stores-redis-1 redis-cli PING </dev/null 2>/dev/null)"
age=$(timeout 10 docker exec -i syboard-stores-age-1 psql -U syboard -d syboard_graph -tAq 2>/dev/null <<'SQL'
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT * FROM cypher('@@GRAPH@@', $$ RETURN 1 $$) AS (x agtype);
SQL
)
echo "age=$age"
echo "--- listeners"
ss -ltnH | awk '{print $4}'
echo "--- end"
"""
SECTIONS = ("node", "secrets_dir", "secrets", "disk", "containers1", "containers2", "stores", "listeners", "end")


def settle():
    """The settle window in seconds: SYBOARD_SETTLE, 0 to 60, default 8."""
    v = os.environ.get("SYBOARD_SETTLE", "8").strip()
    if not v.isdigit() or int(v) > 60:
        raise node.NodeError("SYBOARD_SETTLE is a number of seconds from 0 to 60")
    return int(v)


def survey_script(home, settle_s):
    return (SURVEY.replace("@@D@@", shlex.quote(home)).replace("@@SETTLE@@", str(int(settle_s))).replace("@@FMT@@", FMT)
            .replace("@@GRAPH@@", node.GRAPH))


def mask(x):
    """Evidence as the command shows it: key=value secrets and bare provider keys masked."""
    return KEY_LIKE.sub("<masked>", node.SECRET_LIKE.sub(r"\1\2<masked>", x))


# ---- the checklist ------------------------------------------------------------------------------------------------------------

def checklist(path=None):
    """-> the embedded checklist, or a JSON file of the same shape."""
    if not path:
        return resources.CHECKLIST
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise node.NodeError(f"the checklist {path} could not be read: {e}") from None


def checklist_sha(cl):
    return hashlib.sha256(json.dumps(cl, sort_keys=True).encode()).hexdigest()


def validate(cl, only=None):
    """Refuses a checklist that is not one, that names a check this version does not have, and a module it does not hold."""
    mods = cl.get("modules") if isinstance(cl, dict) else None
    if not isinstance(mods, list) or not mods or not all(isinstance(m, dict) for m in mods):
        raise node.NodeError("the checklist holds no list of modules")
    ids = [m.get("id") for m in mods]
    if not all(isinstance(i, str) and NODE_RE.fullmatch(i) for i in ids) or len(set(ids)) != len(ids) or "unlisted" in ids:
        raise node.NodeError("every module of the checklist has its own id (lower-case letters, digits and dashes; 'unlisted' is the "
                             "coverage row's)")
    for m in mods:
        for cov in m.get("covers") or []:
            if not (isinstance(cov, dict) and (cov.get("name") or (cov.get("project") and cov.get("service")))):
                raise node.NodeError(f"module {m['id']}: each entry of covers names a container, or a Compose project and service")
        if not all(isinstance(m.get(lv) or [], list) for lv in LEVELS):
            raise node.NodeError(f"module {m['id']}: each level is a list of check ids")
    unknown = sorted({c for m in mods for lv in LEVELS for c in m.get(lv) or [] if c not in CHECKS})
    if unknown:
        raise node.NodeError(f"the checklist names checks this version of syboard does not have: {', '.join(map(str, unknown))}")
    if only is not None and only not in ids:
        raise node.NodeError(f"no module {only} on the checklist; its modules: {', '.join(ids)}")


# ---- the survey's facts -------------------------------------------------------------------------------------------------------

def _sections(out):
    parts, cur = {n: [] for n in SECTIONS}, None
    for ln in out.splitlines():
        if ln.startswith("--- ") and ln[4:].strip() in parts:
            cur = ln[4:].strip()
            continue
        if cur:
            parts[cur].append(ln)
    return parts


def parse_survey(out):
    p = _sections(out)
    kv = {}
    for sec in ("node", "stores"):
        for ln in p[sec]:
            k, sep, v = ln.partition("=")
            if sep:
                kv[k.strip()] = v.strip()

    def containers(lines):
        found = {}
        for ln in lines:
            f = ["" if x == "<no value>" else x for x in ln.split("|")]          # a label the container lacks prints "<no value>"
            if len(f) < 9:
                continue
            name = f[0].lstrip("/")
            found[name] = {"name": name, "image": f[1], "image_id": f[2], "state": f[3], "started": f[4], "restarts": f[5],
                           "health": f[6], "project": f[7], "service": f[8]}
        return found

    def entries(lines):
        found = []
        for ln in lines:
            parts = ln.rsplit(" ", 2)
            if len(parts) == 3:
                found.append({"name": os.path.basename(parts[0]), "mode": parts[1], "owner": parts[2]})
        return found
    disk = []
    for ln in p["disk"]:
        parts = ln.split()
        if len(parts) == 2 and parts[1].rstrip("%").isdigit():
            disk.append({"mount": parts[0], "use": int(parts[1].rstrip("%"))})
    return {"kv": kv, "c1": containers(p["containers1"]), "c2": containers(p["containers2"]), "secrets_dir": entries(p["secrets_dir"])[:1],
            "secrets": entries(p["secrets"]), "disk": disk, "listeners": [x.strip() for x in p["listeners"] if x.strip()]}


# ---- the checks: each gives (result, evidence); the result is pass, fail or unknown ----------------------------------------------

def _kv(f, k):
    return f["kv"].get(k, "")


def _covered(f, m):
    """The containers a module covers, matched by Compose project and service, or by name."""
    out = []
    for c in f["c1"].values():
        for cov in m.get("covers") or []:
            if (cov.get("name") and c["name"] == cov["name"]) or (
                    cov.get("project") and c["project"] == cov["project"] and c["service"] == cov.get("service")):
                out.append(c)
                break
    return out


def ck_containers_exist(f, m, ctx):
    cs, want = _covered(f, m), len(m.get("covers") or [])
    if len(cs) < want:
        return "fail", f"{len(cs)} of {want} containers exist ({', '.join(sorted(c['service'] or c['name'] for c in cs)) or 'none'})"
    return "pass", ", ".join(f"{c['name']} {c['image'][:60]}" for c in cs)


def ck_containers_stable(f, m, ctx):
    cs, want = _covered(f, m), len(m.get("covers") or [])
    if len(cs) < want:
        return "fail", f"{len(cs)} of {want} containers exist"
    bad = []
    for c in cs:
        c2 = f["c2"].get(c["name"])
        if c["state"] != "running":
            bad.append(f"{c['name']} {c['state']}")
        elif not c2 or (c2["state"], c2["started"], c2["restarts"]) != (c["state"], c["started"], c["restarts"]):
            bad.append(f"{c['name']} changed within {ctx.get('settle', 0)} s")
    prev = (ctx.get("previous") or {}).get("restarts") or {}
    for c in cs:
        was, now = str(prev.get(c["name"], "")), c["restarts"]
        if was.isdigit() and now.isdigit() and int(now) > int(was):
            bad.append(f"{c['name']} restarted {int(now) - int(was)} time(s) since the last verify")
    if bad:
        return "fail", "; ".join(bad)
    return "pass", "; ".join(f"{c['name']} running since {c['started'][:19]}Z, restarts {c['restarts']}" for c in cs)


def ck_containers_healthy(f, m, ctx):
    cs = _covered(f, m)
    bad = [f"{c['name']} {c['health']}" for c in cs if c["health"] and c["health"] != "healthy"]
    return ("fail", "; ".join(bad)) if bad else ("pass", "; ".join(f"{c['name']} {c['health'] or 'no health check'}" for c in cs))


def ck_docker_answers(f, m, ctx):
    v = _kv(f, "docker")
    return ("pass", f"Docker Engine {v}") if v else ("fail", "Docker does not answer")


def ck_only_ssh_public(f, m, ctx):
    public = [a for a in f["listeners"] if not re.match(r"^(127\.|\[::1\]|::1)", a) and not re.search(r"[:.]22$", a)]
    return ("fail", "listening publicly: " + ", ".join(public)) if public else ("pass", "only SSH listens on a public address")


def ck_disk_space(f, m, ctx):
    if not f["disk"]:
        return "unknown", "df gave no answer"
    full = [f"{x['mount']} {x['use']}%" for x in f["disk"] if x["use"] >= DISK_MAX]
    seen = "; ".join(f"{x['mount']} {x['use']}%" for x in f["disk"])
    return ("fail", f"{DISK_MAX}% or more used: " + ", ".join(full)) if full else ("pass", f"used: {seen}")


def ck_secrets_root_only(f, m, ctx):
    if not f["secrets_dir"]:
        return "fail", "the node has no secrets folder"
    want = set(m.get("secrets") or [])
    missing = sorted(want - {s["name"] for s in f["secrets"]})
    loose = [f"{s['name']} {s['mode']} {s['owner']}" for s in f["secrets_dir"] + f["secrets"]
             if s["owner"] != "root" or not ROOT_ONLY.match(s["mode"])]
    if missing or loose:
        return "fail", "; ".join(([f"missing: {', '.join(missing)}"] if missing else []) + ([f"not root-only: {', '.join(loose)}"] if loose else []))
    return "pass", f"the folder and its {len(f['secrets'])} entries are root-only (no group or other permission); names only, no value read"


def ck_es_health(f, m, ctx):
    st = (re.search(r'"status"\s*:\s*"(\w+)"', _kv(f, "es")) or [None, ""])[1]
    s = _kv(f, "es_search")
    ok = st in ("green", "yellow") and s == "200"
    return ("pass" if ok else "fail"), f"cluster {st or 'no answer'}, a search answers {s or 'nothing'}"


def ck_age_cypher(f, m, ctx):
    v = _kv(f, "age")
    return ("pass", f"Cypher RETURN 1 on the graph {node.GRAPH} answers 1") if v == "1" else ("fail", f"Cypher on the graph {node.GRAPH} answered '{v}'")


def ck_nats_jetstream(f, m, ctx):
    return ("pass", "JetStream is on, store /data") if _kv(f, "jetstream") not in ("", "0") else ("fail", "JetStream is not reported on")


def ck_redis_ping(f, m, ctx):
    v = _kv(f, "redis")
    return ("pass", "PONG") if v == "PONG" else ("fail", f"PING answered '{v}'")


CHECKS = {
    "docker_answers": ck_docker_answers, "only_ssh_public": ck_only_ssh_public, "disk_space": ck_disk_space,
    "secrets_root_only": ck_secrets_root_only, "containers_exist": ck_containers_exist, "containers_stable": ck_containers_stable,
    "containers_healthy": ck_containers_healthy, "es_health": ck_es_health, "age_cypher": ck_age_cypher,
    "nats_jetstream": ck_nats_jetstream, "redis_ping": ck_redis_ping,
}


# ---- the rows -----------------------------------------------------------------------------------------------------------------

def image_version(image):
    """The image a module runs, as the report shows it: its name without the registry, then its tag, or the first 12 characters
    of its digest (docker.elastic.co/elasticsearch/elasticsearch@sha256:0123... -> elasticsearch@0123456789ab)."""
    name, _, digest = image.partition("@")
    short = name.split("/")[-1]
    if digest:
        short += "@" + digest.split(":")[-1][:12]
    return short[:60]


def evaluate(cl, facts, ctx, only=None):
    """-> the rows. Coverage is judged over every module; with only, the rows hold that module alone and no coverage row."""
    rows, covered = [], set()
    for m in cl["modules"]:
        cs = _covered(facts, m)
        covered.update(c["name"] for c in cs)
        if only is not None and m["id"] != only:
            continue
        levels = {}
        for lv in LEVELS:
            checks = []
            for cid in m.get(lv) or []:
                res, ev = CHECKS[cid](facts, m, ctx)
                checks.append({"id": cid, "result": res, "evidence": mask(ev)[:200]})
            levels[lv] = {"result": ("none" if not checks else "fail" if any(c["result"] == "fail" for c in checks)
                                     else "unknown" if any(c["result"] == "unknown" for c in checks) else "pass"),
                          "checks": checks}
        res = [levels[lv]["result"] for lv in LEVELS if levels[lv]["result"] != "none"]
        rows.append({"module": m["id"], "name": m.get("name", m["id"]), "@type": "SoftwareApplication",
                     "softwareVersion": m.get("softwareVersion") or (image_version(cs[0]["image"]) if cs else ""),
                     "containers": [c["name"] for c in cs], "levels": levels,
                     "row": "fail" if "fail" in res else "unknown" if ("unknown" in res or not res) else "pass",
                     "fix": m.get("fix", "")})
    if only is not None:
        return rows
    unlisted = sorted(n for n in facts["c1"] if n not in covered)
    none = {"result": "none", "checks": []}
    check = ({"id": "coverage", "result": "fail", "evidence": mask("not on the checklist: " + ", ".join(unlisted))[:200]} if unlisted
             else {"id": "coverage", "result": "pass", "evidence": f"all {len(facts['c1'])} containers are on the checklist"})
    rows.append({"module": "unlisted", "name": "every container belongs to a module", "@type": "SoftwareApplication",
                 "softwareVersion": "", "containers": unlisted,
                 "levels": {"present": {"result": check["result"], "checks": [check]}, "running": none, "working": none},
                 "row": check["result"],
                 "fix": "add a module for it to a checklist given with --checklist, or remove the container" if unlisted else ""})
    return rows


def run(T, name, cl, previous=None, only=None, at=""):
    """One verify run over transport T: the survey, then the rows. -> the result; nothing is written anywhere. A machine that is not
    the node gives {"refused": why} and no rows; a machine that does not answer gives reachable False and no rows."""
    if not NODE_RE.fullmatch(name or ""):
        raise node.NodeError("the node's name is lower-case letters, digits and dashes, 1 to 63 of them")
    validate(cl, only)
    s = settle()
    script = survey_script(node.tcfg()["home"], s)
    n0 = len(T.log)
    rc, out = T.run(script, timeout=TIMEOUT)
    base = {"node": name, "at": at, "only": only, "writes_on_node": 0,
            "sent": [hashlib.sha256(x.encode()).hexdigest() for x in T.log[n0:] if not x.startswith("put ")],
            "checklist": {"id": cl.get("id", ""), "version": cl.get("version", ""), "sha256": checklist_sha(cl)}}
    if "--- end" not in out:
        return dict(base, reachable=False, rc=rc, error=mask(out.strip()[-300:]), rows=[], summary={"result": "unreachable"})
    facts = parse_survey(out)
    nid = _kv(facts, "node_id")
    if nid != name:
        home = node.tcfg()["home"]
        why = (f"this machine is not the node {name}: its {home}/stores/node.env names '{nid}'" if nid
               else f"this machine is not the node {name}: it has no NODE_ID in {home}/stores/node.env (syboard node plan shows "
                    f"what an install would do)")
        return dict(base, reachable=True, refused=why, rows=[], summary={"result": "refused"})
    rows = evaluate(cl, facts, {"previous": previous or {}, "settle": s}, only)
    n = {k: sum(r["row"] == k for r in rows) for k in ("pass", "fail", "unknown")}
    return dict(base, reachable=True, rows=rows, summary={
        "result": "pass" if not n["fail"] and not n["unknown"] else "fail", "rows": len(rows), **n,
        # each container's restart count as seen after the settle window, the next run's baseline
        "restarts": {nm: (facts["c2"].get(nm) or c)["restarts"] for nm, c in facts["c1"].items()}})


MARK = {"pass": "ok", "fail": "FAIL", "unknown": "?", "none": "-"}


def report(res):
    """-> the lines the command prints: a head line, then one line per row with its three levels; under a row that did not pass,
    each failed or unread check with its evidence, then the module's fix."""
    cl, sm = res.get("checklist") or {}, res.get("summary") or {}
    scope = f"module {res['only']} only" if res.get("only") else f"{sm.get('pass', 0)} of {sm.get('rows', 0)} rows pass"
    lines = [f"{res['node']}: {scope}; checklist {cl.get('id') or '-'} version {cl.get('version') or '-'} "
             f"(sha256 {(cl.get('sha256') or '')[:12]}); nothing was written on the node"]
    w = max([len(r["module"]) for r in res["rows"]] + [8])
    wv = max([len(r["softwareVersion"] or "-") for r in res["rows"]] + [1])
    for r in res["rows"]:
        levels = ", ".join(f"{lv} {MARK[r['levels'][lv]['result']]}" for lv in LEVELS)
        lines.append(f"  {MARK[r['row']]:<4}  {r['module']:<{w}}  {r['softwareVersion'] or '-':<{wv}}  ({levels})")
        for lv in LEVELS:
            lines += [f"        {lv} {c['id']}: {c['evidence']}" for c in r["levels"][lv]["checks"] if c["result"] != "pass"]
        if r["row"] != "pass" and r["fix"]:
            lines.append(f"        fix: {r['fix']}")
    return lines


# ---- the records --------------------------------------------------------------------------------------------------------------

def records(name, res):
    """-> one record per module and, for a full run, a summary. A refused run gives none (the machine is not the node); a one-module
    run gives only its module's record, so the last full run stays the node's summary and its restart baseline."""
    if res.get("refused"):
        return []
    at, out = res.get("at", ""), []
    for r in res["rows"]:
        out.append({"at": at, "record": f"node-verify:{name}:{r['module']}", "row": r["row"], "softwareVersion": r["softwareVersion"],
                    **{lv: r["levels"][lv]["result"] for lv in LEVELS},
                    "evidence": "; ".join(f"{lv}: {c['id']} {c['result']} ({c['evidence']})"
                                          for lv in LEVELS for c in r["levels"][lv]["checks"])[:2000],
                    "containers": ", ".join(r["containers"]), "fix": r["fix"]})
    if res.get("only") is not None:
        return out
    sm, cl = res.get("summary") or {}, res.get("checklist") or {}
    out.append({"at": at, "record": f"node-verify:{name}", "result": sm.get("result", ""), "rows": sm.get("rows", 0),
                "pass": sm.get("pass", 0), "fail": sm.get("fail", 0), "unknown": sm.get("unknown", 0),
                "checklist": f"{cl.get('id', '')} version {cl.get('version', '')}", "checklist_sha256": cl.get("sha256", ""),
                "sent": res.get("sent") or [], "writes_on_node": 0, "restarts": sm.get("restarts") or {}})
    return out


def previous(path, name):
    """{"restarts": {container: count}} from the node's last full run that reached it, read from the records file at path; {} when
    there is none."""
    last = None
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                try:
                    rec = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("record") == f"node-verify:{name}" and rec.get("result") in ("pass", "fail"):
                    last = rec
    except OSError:
        return {}
    return {"restarts": last.get("restarts") or {}} if last else {}
