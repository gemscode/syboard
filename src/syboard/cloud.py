# Copyright 2026 The Syboard Authors
# SPDX-License-Identifier: Apache-2.0
"""A node's machine as its cloud provider sees it, read only: the Hetzner Cloud API with a project's API token.

It shows what SSH cannot when a machine stops answering: the server's status, its firewalls and their rules, the provider's
actions on it (power, reset, reboot, backups, rescale, rebuild) and its graphs (cpu, disk, network).

Only GET requests are sent: the module has no other verb, so a token that also allows writes changes nothing through it. The
token is read from the environment variable HETZNER_API_KEY, or from a .env file named with --env-file; it goes in the
Authorization header, never in an address, and it is never printed, logged or returned. A redirect is not followed.

The tests point SYBOARD_CLOUD_API at a local stand-in for the API. Any other address is refused: the token goes only to
https://api.hetzner.cloud/v1, or to a stand-in over http on this machine's loopback; no proxy is used."""
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

KEY = "HETZNER_API_KEY"
VIEWS = ("all", "server", "actions", "metrics")
METRIC_TYPES = ("cpu", "disk", "network")
MAX_PAGES = 20                                     # a bound on the search by address
# the provider's series names, their labels here and the factor to the unit shown
LABELS = {"cpu": ("cpu", "%", 1.0),
          "network.0.bandwidth.in": ("in", "kB/s", 0.001), "network.0.bandwidth.out": ("out", "kB/s", 0.001),
          "network.0.pps.in": ("pps in", "", 1.0), "network.0.pps.out": ("pps out", "", 1.0),
          "disk.0.iops.read": ("iops r", "", 1.0), "disk.0.iops.write": ("iops w", "", 1.0),
          "disk.0.bandwidth.read": ("disk r", "kB/s", 0.001), "disk.0.bandwidth.write": ("disk w", "kB/s", 0.001)}


class CloudError(Exception):
    """A refusal or a failed read. Its text never holds the token."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None                                # not followed: the Authorization header would go with it


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)     # no proxy, no redirect
API = "https://api.hetzner.cloud/v1"
LOOPBACK = ("127.0.0.1", "::1", "localhost")


def api():
    """Hetzner's own address, or a stand-in for the tests over http on this machine's loopback. Any other value of
    SYBOARD_CLOUD_API is refused, so an environment variable can never send the token elsewhere."""
    a = os.environ.get("SYBOARD_CLOUD_API", API).rstrip("/")
    if a == API:
        return a
    u = urllib.parse.urlparse(a)
    if u.scheme == "http" and u.hostname in LOOPBACK:
        return a
    raise CloudError(f"SYBOARD_CLOUD_API must be {API}, or http on this machine's loopback for the tests: nothing was read")


def env_value(path, name):
    """One value of a .env file, or None."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(.*?)\s*$", line)
                if m and m.group(1) == name:
                    v = m.group(2)
                    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"" else v
    except OSError:
        return None
    return None


def token(name=KEY, env_file=None):
    v = env_value(env_file, name) if env_file else os.environ.get(name)
    where = env_file or "the environment"
    if not v:
        raise CloudError(f"{name} is not set in {where}: nothing was read from the provider")
    if not re.fullmatch(r"[A-Za-z0-9]{20,128}", v):
        raise CloudError(f"{name} in {where} is not in the form of an API token (20 to 128 letters and digits): nothing was read")
    return v


class Client:
    """GET only. The token stays in this object and leaves it only in the Authorization header of a request."""

    def __init__(self, tok, base=None, timeout=30):
        self._tok, self.base, self.timeout, self.log = tok, (base or api()), timeout, []

    def scrub(self, text):
        return str(text).replace(self._tok, "<token>")

    def get(self, path, **params):
        path = path.lstrip("/")
        q = urllib.parse.urlencode([(k, v) for k, v in params.items() if v is not None])
        url = f"{self.base}/{path}" + (f"?{q}" if q else "")
        if self._tok in url:
            raise CloudError(f"refused: the request for /{path} would carry the token in its address")
        self.log.append("GET /" + path + (f"?{q}" if q else ""))
        try:
            req = urllib.request.Request(url, method="GET", headers={"Authorization": f"Bearer {self._tok}",
                                                                     "Accept": "application/json", "User-Agent": "syboard"})
            with _OPENER.open(req, timeout=self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                err = (json.load(e) or {}).get("error") or {}
            except Exception:
                err = {}
            raise CloudError(self.scrub(f"the provider refused GET /{path}: HTTP {e.code} {err.get('code') or ''} "
                                        f"{err.get('message') or ''}".strip())) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise CloudError(self.scrub(f"the provider did not answer GET /{path}: {getattr(e, 'reason', None) or e}")) from None


def find_server(cl, name, host=None):
    """The server: by its name, else by its public IPv4 address (an address given as the name is searched as an address)."""
    if host is None and re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", name):
        name, host = None, name
    found = cl.get("servers", name=name).get("servers") or [] if name else []
    page = 1
    while not found and host and page and page <= MAX_PAGES:
        r = cl.get("servers", page=page, per_page=50)
        found = [x for x in r.get("servers") or [] if ((x.get("public_net") or {}).get("ipv4") or {}).get("ip") == host]
        page = ((r.get("meta") or {}).get("pagination") or {}).get("next_page")
    if not found:
        raise CloudError(f"no server named {name or '-'}" + (f" or at {host}" if host else "") + " in the token's project")
    return found[0]


def rule_line(r):
    inbound = r.get("direction") == "in"
    ips = r.get("source_ips") if inbound else r.get("destination_ips")
    return (f"{r.get('direction')} {r.get('protocol')} {r.get('port') or '-'} {'from' if inbound else 'to'} {', '.join(ips or []) or '-'}"
            + (f" ({r['description']})" if r.get("description") else ""))


def server_view(cl, s):
    pn = s.get("public_net") or {}
    v4, v6 = pn.get("ipv4") or {}, pn.get("ipv6") or {}
    st, dc, im = s.get("server_type") or {}, s.get("datacenter") or {}, s.get("image") or {}
    loc = s.get("location") or dc.get("location") or {}
    firewalls = []
    for f in pn.get("firewalls") or []:
        try:
            fw = cl.get(f"firewalls/{f.get('id')}").get("firewall") or {}
            firewalls.append({"name": fw.get("name"), "status": f.get("status"), "rules": [rule_line(r) for r in fw.get("rules") or []]})
        except CloudError as e:
            firewalls.append({"id": f.get("id"), "status": f.get("status"), "error": str(e)})
    return {"id": s.get("id"), "name": s.get("name"), "status": s.get("status"), "created": s.get("created"),
            "type": f"{st.get('name')} ({st.get('cores')} vCPU, {st.get('memory')} GB, {st.get('disk')} GB disk, {st.get('cpu_type')}, "
                    f"{st.get('architecture')})",
            "location": f"{dc.get('name') or loc.get('name')} ({loc.get('city')}, {loc.get('network_zone')})",
            "image": f"{im.get('name')} ({im.get('os_flavor')} {im.get('os_version')})" if im else None,
            "ipv4": v4.get("ip"), "ipv4_blocked": v4.get("blocked"), "ipv6": v6.get("ip"), "ipv6_blocked": v6.get("blocked"),
            "private": [p.get("ip") for p in s.get("private_net") or []],
            "locked": s.get("locked"), "rescue": s.get("rescue_enabled"), "backup_window": s.get("backup_window"),
            "protection": s.get("protection"), "labels": s.get("labels"), "placement_group": (s.get("placement_group") or {}).get("name"),
            "traffic_bytes": {"out": s.get("outgoing_traffic"), "in": s.get("ingoing_traffic"), "included": s.get("included_traffic")},
            "volumes": len(s.get("volumes") or []), "firewalls": firewalls}


def actions_view(cl, sid, limit=25):
    """The provider's actions on the server, the newest first."""
    acts = cl.get(f"servers/{sid}/actions", sort="started:desc", per_page=limit).get("actions") or []
    return [{"command": a.get("command"), "status": a.get("status"), "started": a.get("started"), "finished": a.get("finished"),
             "error": (a.get("error") or {}).get("message")} for a in acts]


def when(x, default):
    """An instant as RFC 3339 in UTC; a time without a zone is taken as UTC."""
    if not x:
        return default
    try:
        t = dt.datetime.fromisoformat(x.strip().replace(" ", "T").replace("Z", "+00:00"))
    except ValueError:
        raise CloudError(f"'{x}' is not a time (give it as 2026-01-31T08:30:00Z)")
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc)


def _num(v, factor):
    try:
        x = float(v) * factor
    except (TypeError, ValueError):
        return "-"
    return "-" if x != x else f"{x:.1f}"


def metrics_view(cl, sid, start, end, step):
    """One line per step from start to end: every series the provider returns, the known ones under a short label. The provider
    returns the network and disk series at five-minute steps and leaves them empty at one-minute steps."""
    series = {}
    for t in METRIC_TYPES:
        m = cl.get(f"servers/{sid}/metrics", type=t, start=start.isoformat(), end=end.isoformat(), step=step).get("metrics") or {}
        for name, ts in (m.get("time_series") or {}).items():
            series[name] = {int(round(float(p[0]))): p[1] for p in ts.get("values") or []}
    names = [n for n in LABELS if n in series] + sorted(n for n in series if n not in LABELS)
    rows = []
    for t in sorted(set().union(*series.values())) if series else []:
        cells = []
        for n in names:
            label, unit, factor = LABELS.get(n, (n, "", 1.0))
            cells.append(f"{label} {_num(series[n].get(t), factor)}{(' ' + unit) if unit else ''}")
        rows.append(dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + "  " + "  ".join(cells))
    return {"start": start.isoformat(), "end": end.isoformat(), "step_s": step, "series": names, "rows": rows}


def read(server, what="all", start=None, end=None, step=300, key=KEY, env_file=None):
    """The server as the provider sees it: what="all" (server, actions, metrics) or one of them. Read only: GET requests."""
    if what not in VIEWS:
        raise CloudError(f"--what is one of {', '.join(VIEWS)}")
    step = int(step)
    if not 10 <= step <= 86400:
        raise CloudError("--step is 10 to 86400 seconds")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    b = when(end, now)
    a = when(start, b - dt.timedelta(hours=1))
    if a >= b:
        raise CloudError("--start must come before --end")
    base = api()                                    # the address is checked before the token is read
    tok = token(key, env_file)
    cl = Client(tok, base)
    try:
        s = find_server(cl, server)
        out = {"server_asked": server, "provider": "hetzner", "read_at": now.isoformat(),
               "server": server_view(cl, s) if what in ("all", "server") else {"id": s.get("id"), "name": s.get("name"),
                                                                               "status": s.get("status")}}
        if what in ("all", "actions"):
            out["actions"] = actions_view(cl, s.get("id"))
        if what in ("all", "metrics"):
            out["metrics"] = metrics_view(cl, s.get("id"), a, b, step)
    except CloudError as e:
        raise CloudError(cl.scrub(e)) from None
    except Exception as e:                           # a backstop: nothing leaves the module unmasked
        raise CloudError(cl.scrub(f"{type(e).__name__}: {e}")) from None
    out["requests"] = list(cl.log)                  # every request sent: GET, its path and its query (the token is never in them)
    if tok in json.dumps(out):
        raise CloudError("the answer held the token, so nothing is shown")
    return out
