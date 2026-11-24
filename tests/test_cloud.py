# Copyright 2026 The Syboard Authors
# SPDX-License-Identifier: Apache-2.0
"""syboard cloud against a local stand-in for the Hetzner Cloud API: canned answers in its documented shapes and a scratch
.env with a made-up token. It checks the views of the server, its firewalls, its actions and its graphs; that only GET
requests leave; that the token goes only in the Authorization header and is in no address, no answer and no refusal; that a
redirect is not followed; the refusals; and the syboard command itself. Usage: python tests/test_cloud.py"""
import datetime as dt
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")
sys.path.insert(0, SRC)
from syboard import cloud  # noqa: E402

TOKEN = ("FakeToken0123456789" * 4)[:64]           # made up: 64 letters and digits, like a provider's token
WRONG = ("WrongToken987654321" * 4)[:64]
ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))


T0 = int(dt.datetime(2026, 1, 31, 8, 55, tzinfo=dt.timezone.utc).timestamp())
TIMES = [T0 + 60 * i for i in range(6)]            # 08:55 to 09:00, one a minute
SERVER = {"id": 42, "name": "test-server", "status": "running", "created": "2026-01-30T07:40:00+00:00",
          "public_net": {"ipv4": {"ip": "192.0.2.10", "blocked": False, "dns_ptr": "static.example"},
                         "ipv6": {"ip": "2001:db8::/64", "blocked": False}, "firewalls": [{"id": 7, "status": "applied"}]},
          "private_net": [{"network": 3, "ip": "10.1.0.5", "alias_ips": []}],
          "server_type": {"name": "cx32", "cores": 4, "memory": 8.0, "disk": 80, "cpu_type": "shared", "architecture": "x86"},
          "location": {"name": "fsn1", "city": "Falkenstein", "network_zone": "eu-central"},     # the server's location, at the top level as the API gives it
          "image": {"name": "debian-13", "os_flavor": "debian", "os_version": "13"},
          "rescue_enabled": False, "locked": False, "backup_window": "22-02", "outgoing_traffic": 1000, "ingoing_traffic": 2000,
          "included_traffic": 21990232555520, "protection": {"delete": False, "rebuild": False}, "labels": {"role": "node"},
          "volumes": [], "placement_group": {"name": "test-group", "type": "spread"}}
FIREWALL = {"id": 7, "name": "test-firewall", "rules": [
    {"direction": "in", "protocol": "tcp", "port": "22", "source_ips": ["203.0.113.7/32"], "destination_ips": [],
     "description": "ssh from the operator"},
    {"direction": "in", "protocol": "icmp", "port": None, "source_ips": ["203.0.113.7/32"], "destination_ips": []}]}
ACTIONS = [{"id": 3, "command": "start_server", "status": "success", "started": "2026-01-30T07:41:00+00:00",
            "finished": "2026-01-30T07:41:20+00:00", "progress": 100, "error": None},
           {"id": 2, "command": "assign_primary_ip", "status": "success", "started": "2026-01-30T07:40:30+00:00",
            "finished": "2026-01-30T07:40:40+00:00", "progress": 100, "error": None},
           {"id": 1, "command": "create_server", "status": "success", "started": "2026-01-30T07:40:00+00:00",
            "finished": "2026-01-30T07:40:30+00:00", "progress": 100, "error": None}]


def vals(xs):
    return {"values": [[t, x] for t, x in zip(TIMES, xs)]}


METRICS = {"cpu": {"cpu": vals(["3.5", "4.0", "98.0", "97.5", "NaN", "2.0"])},
           "disk": {"disk.0.iops.read": vals(["1", "1", "0", "0", "0", "1"]), "disk.0.iops.write": vals(["5", "6", "0", "0", "0", "4"]),
                    "disk.0.bandwidth.read": vals(["1000", "1000", "0", "0", "0", "1000"]),
                    "disk.0.bandwidth.write": vals(["20000", "21000", "0", "0", "0", "15000"]),
                    "disk.0.extra": vals(["7", "7", "7", "7", "7", "7"])},
           "network": {"network.0.bandwidth.in": vals(["5000", "5200", "4800", "0", "0", "0"]),
                       "network.0.bandwidth.out": vals(["900000", "950000", "870000", "0", "0", "0"]),
                       "network.0.pps.in": vals(["40", "42", "39", "0", "0", "0"]),
                       "network.0.pps.out": vals(["700", "720", "680", "0", "0", "0"])}}
SEEN = []


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, headers=()):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        SEEN.append({"method": "GET", "path": u.path, "query": q, "auth": self.headers.get("Authorization"), "raw": self.path})
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401, {"error": {"code": "unauthorized", "message": "unable to authenticate"}})
        page = {"meta": {"pagination": {"page": 1, "next_page": None}}}
        if u.path == "/v1/servers":
            name = q.get("name")
            if name == "redirect-me":
                return self._send(302, {}, [("Location", f"http://127.0.0.1:{self.server.server_address[1]}/v1/servers?name=test-server")])
            return self._send(200, dict(page, servers=[SERVER] if name in (None, "test-server") else []))
        if u.path == "/v1/servers/42/actions":
            return self._send(200, dict(page, actions=ACTIONS))
        if u.path == "/v1/servers/42/metrics":
            t = q.get("type")
            if t not in METRICS or not (q.get("start") and q.get("end") and q.get("step")):
                return self._send(400, {"error": {"code": "invalid_input", "message": "type, start, end and step are required"}})
            return self._send(200, {"metrics": {"start": q["start"], "end": q["end"], "step": int(q["step"]), "time_series": METRICS[t]}})
        if u.path == "/v1/firewalls/7":
            return self._send(200, {"firewall": FIREWALL})
        return self._send(404, {"error": {"code": "not_found", "message": "not found"}})

    def _other(self):
        SEEN.append({"method": self.command, "path": self.path, "auth": self.headers.get("Authorization"), "raw": self.path})
        self._send(405, {"error": {"code": "method_not_allowed", "message": "fake: only GET"}})

    do_POST = do_PUT = do_DELETE = do_PATCH = _other


def refusal(fn):
    try:
        fn()
    except cloud.CloudError as e:
        return str(e)
    return None


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = tempfile.mkdtemp(prefix="cloud-fake-")
    envs = {}
    for name, text in (("ok", f"# HETZNER API KEY\nHETZNER_API_KEY={TOKEN}\nOTHER=1\n"), ("wrong", f"HETZNER_API_KEY={WRONG}\n"),
                       ("none", "OTHER=1\n"), ("bad", "HETZNER_API_KEY=abc-def\n")):
        envs[name] = os.path.join(tmp, f"{name}.env")
        with open(envs[name], "w") as f:
            f.write(text)
    api = f"http://127.0.0.1:{port}/v1"
    os.environ["SYBOARD_CLOUD_API"] = api
    OK = envs["ok"]
    try:
        # 1. the whole view
        out = cloud.read("test-server", start="2026-01-31T08:55:00Z", end="2026-01-31T09:00:00Z", step=60, env_file=OK)
        s = out["server"]
        check("the server's status, type and location", s["status"] == "running" and s["type"].startswith("cx32 (4 vCPU, 8.0 GB")
              and s["location"] == "fsn1 (Falkenstein, eu-central)", f"{s['status']}, {s['type']}, {s['location']}")
        check("its addresses, block flags, private address and placement group", s["ipv4"] == "192.0.2.10" and s["ipv4_blocked"] is False
              and s["private"] == ["10.1.0.5"] and s["placement_group"] == "test-group")
        fw = s["firewalls"][0] if s["firewalls"] else {}
        check("its firewall and the firewall's rules", fw.get("name") == "test-firewall" and fw.get("status") == "applied"
              and fw.get("rules") == ["in tcp 22 from 203.0.113.7/32 (ssh from the operator)", "in icmp - from 203.0.113.7/32"],
              json.dumps(fw.get("rules")))
        acts = [a["command"] for a in out["actions"]]
        check("the provider's actions, the newest first", acts == ["start_server", "assign_primary_ip", "create_server"], ", ".join(acts))
        rows = out["metrics"]["rows"]
        check("one graph line a minute over the window", len(rows) == 6 and rows[0].startswith("2026-01-31 08:55:00")
              and rows[-1].startswith("2026-01-31 09:00:00"), f"{len(rows)} lines")
        check("the known series under their labels, in kB/s", "cpu 3.5 %" in rows[0] and "in 5.0 kB/s" in rows[0]
              and "out 900.0 kB/s" in rows[0] and "pps in 40.0" in rows[0] and "disk w 20.0 kB/s" in rows[0], rows[0])
        check("the network going quiet shows at 08:58", "in 0.0 kB/s" in rows[3] and "pps out 0.0" in rows[3], rows[3])
        check("a value that is not a number shows as -", "cpu - %" in rows[4], rows[4])
        check("a series it does not know is still shown, under its own name", "disk.0.extra 7.0" in rows[0]
              and out["metrics"]["series"][-1] == "disk.0.extra")
        mq = [x["query"] for x in SEEN if x["path"] == "/v1/servers/42/metrics"]
        check("one metrics request per type with the window and the step", [q.get("type") for q in mq] == ["cpu", "disk", "network"]
              and all(q.get("start") == "2026-01-31T08:55:00+00:00" and q.get("end") == "2026-01-31T09:00:00+00:00"
                      and q.get("step") == "60" for q in mq), json.dumps(mq[:1]))
        aq = [x["query"] for x in SEEN if x["path"] == "/v1/servers/42/actions"]
        check("the actions are asked newest first", aq and aq[0].get("sort") == "started:desc", json.dumps(aq[:1]))
        check("the answer lists the requests it sent, all GET", out["requests"] and all(r.startswith("GET /") for r in out["requests"]),
              f"{len(out['requests'])} requests")
        blob = json.dumps(out)
        check("the token is not in the answer", TOKEN not in blob)

        # 2. lookups
        o2 = cloud.read("192.0.2.10", what="server", env_file=OK)
        check("a server not found by name is found by its public address", o2["server"]["id"] == 42 and "actions" not in o2
              and "metrics" not in o2)
        n0 = len(SEEN)
        e = refusal(lambda: cloud.read("redirect-me", what="server", env_file=OK))
        check("a redirect is not followed", e and "HTTP 302" in e and len(SEEN) == n0 + 1, e or "no refusal")
        e = refusal(lambda: cloud.read("nobody", what="server", env_file=OK))
        check("no such server is refused by name", e and "no server named nobody" in e, e or "no refusal")

        # 3. refusals about the key, and what reached the provider
        n0 = len(SEEN)
        e = refusal(lambda: cloud.read("test-server", env_file=envs["none"]))
        check("no key: refused, naming the key, and nothing sent", e and "HETZNER_API_KEY is not set" in e and len(SEEN) == n0,
              e or "no refusal")
        e = refusal(lambda: cloud.read("test-server", env_file=envs["bad"]))
        check("a key not in a token's form: refused, its value not shown, nothing sent", e and "not in the form" in e and "abc-def" not in e
              and len(SEEN) == n0, e or "no refusal")
        e = refusal(lambda: cloud.read("test-server", env_file=envs["wrong"]))
        check("a wrong token: the provider's refusal, without the token", e and "HTTP 401 unauthorized" in e and WRONG not in e,
              e or "no refusal")
        e = refusal(lambda: cloud.read("test-server", what="everything", env_file=OK))
        check("an unknown view is refused before any request", e and "--what is one of" in e, e or "no refusal")
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            closed = sk.getsockname()[1]
        os.environ["SYBOARD_CLOUD_API"] = f"http://127.0.0.1:{closed}/v1"
        e = refusal(lambda: cloud.read("test-server", what="server", env_file=OK))
        check("a provider that does not answer is a refusal, without the token", e and "did not answer" in e and TOKEN not in e,
              e or "no refusal")
        os.environ["SYBOARD_CLOUD_API"] = api

        others = [x for x in SEEN if x["method"] != "GET"]
        check("only GET requests reached the provider", not others, json.dumps(others[:2]))
        tok_ok = [x for x in SEEN if x["auth"] == f"Bearer {TOKEN}"]
        check("the token went only in the Authorization header, in no address",
              tok_ok and not any(TOKEN in x["raw"] or WRONG in x["raw"] for x in SEEN), f"{len(tok_ok)} requests with it")

        # 3b. the token goes only to Hetzner's address, or to a stand-in on this machine's loopback
        n0 = len(SEEN)
        for label, value in (("an http address of another host", "http://api.example.invalid/v1"),
                             ("an https address of another host", "https://api.example.invalid/v1"),
                             ("an empty address", ""), ("an address with no scheme", "api.hetzner.cloud/v1")):
            os.environ["SYBOARD_CLOUD_API"] = value
            e = refusal(lambda: cloud.read("test-server", what="server", env_file=OK))
            check(f"{label} is refused before the token is read or sent", e and "SYBOARD_CLOUD_API must be" in e and len(SEEN) == n0
                  and TOKEN not in e, e or "-")
        os.environ["SYBOARD_CLOUD_API"] = api

        # 4. the syboard command itself
        env = dict(os.environ, SYBOARD_CLOUD_API=api, PYTHONPATH=SRC)
        env.pop("HETZNER_API_KEY", None)
        p = subprocess.run([sys.executable, "-m", "syboard", "cloud", "test-server", "--what", "server", "--env-file", OK, "--json"],
                           capture_output=True, text=True, timeout=120, env=env)
        try:
            hout = json.loads(p.stdout)
        except ValueError:
            hout = {}
        check("syboard cloud answers with the server's view", p.returncode == 0 and (hout.get("server") or {}).get("status") == "running",
              (p.stderr or p.stdout)[-300:])
        check("the token is not in the command's output", TOKEN not in p.stdout + p.stderr)
        p = subprocess.run([sys.executable, "-m", "syboard", "cloud", "test-server", "--env-file", OK],
                           capture_output=True, text=True, timeout=120, env=env)
        check("syboard cloud prints a readable view", p.returncode == 0 and "test-server  running" in p.stdout and "firewall test-firewall" in p.stdout,
              (p.stderr or p.stdout)[-300:])
        env2 = dict(env, HETZNER_API_KEY=TOKEN)
        p = subprocess.run([sys.executable, "-m", "syboard", "cloud", "test-server", "--what", "actions", "--json"],
                           capture_output=True, text=True, timeout=120, env=env2)
        check("the token can come from the environment variable", p.returncode == 0 and TOKEN not in p.stdout + p.stderr,
              (p.stderr or p.stdout)[-200:])
        p = subprocess.run([sys.executable, "-m", "syboard", "cloud", "test-server", "--step", "x"], capture_output=True, text=True,
                           timeout=120, env=env)
        check("syboard cloud refuses a bad option with its reason", p.returncode != 0 and "invalid int value" in p.stderr, p.stderr.strip()[-160:])
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
