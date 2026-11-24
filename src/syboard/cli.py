# Copyright 2026 The Syboard Authors
# SPDX-License-Identifier: Apache-2.0
"""The syboard command."""
import argparse
import json
import os
import re
import sys
import time

from . import __version__, cloud, node

NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
MARK = {"pass": "ok  ", "warn": "warn", "fail": "FAIL", "install": "add ", "set": "set "}


def _key(path):
    p = os.path.expanduser(path)
    if not os.path.isfile(p):
        raise SystemExit(f"syboard: no SSH key at {p}")
    return p


def _name(args):
    n = args.name or "syboard-node"
    if not NAME_RE.match(n):
        raise SystemExit("syboard: --name is lower-case letters, digits and dashes, 1 to 63 of them")
    return n


def _print_plan(p):
    w = max(len(r["id"]) for r in p["assessment"])
    for r in p["assessment"]:
        line = f"  {MARK.get(r['status'], r['status'])}  {r['id']:<{w}}  {r['measured']}"
        print(line + (f"  ({r['note']})" if r.get("note") else ""))
    print("steps: " + ", ".join(f"{s['step']} {'done' if s['done'] else 'to do'}" for s in p["steps"]))
    if p["refuse"]:
        print("refused: below the minimum for " + ", ".join(p["refuse"]))


def _log_step(host, name, res):
    folder = os.path.expanduser("~/.syboard/deployments")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, re.sub(r"[^A-Za-z0-9._-]", "_", host) + ".jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "step": name, "result": res.get("result")}) + "\n")


def cmd_plan(args):
    T = node.SSH(args.host, _key(args.ssh_key), args.user)
    p = node.plan(T, _name(args), args.requirements)
    print(json.dumps(p, indent=1)) if args.json else _print_plan(p)
    return 1 if p["refuse"] else 0


def cmd_install(args):
    if not args.apply:
        rc = cmd_plan(args)
        if not args.json:
            print("nothing was changed: run again with --apply to install")
        return rc
    T = node.SSH(args.host, _key(args.ssh_key), args.user)

    def on_step(name, res):
        _log_step(args.host, name, res)
        if not args.json:
            print(f"  {name}: {res['result']}", flush=True)
    out = node.apply(T, _name(args), on_step=on_step, reqs_path=args.requirements)
    if args.json:
        print(json.dumps(out, indent=1))
    else:
        print(f"installed: every step done on {args.host} ({len(T.log)} commands over one SSH connection)")
    return 0


def cmd_journal(args):
    T = node.SSH(args.host, _key(args.ssh_key), args.user)
    out = node.journal(T, args.since, args.until, grep=args.grep, lines=args.lines)
    if args.json:
        print(json.dumps(out, indent=1))
        return 0
    print(f"# booted {out['booted_utc']} UTC, up {out['uptime']}")
    for b in out["boots"]:
        print(f"#   {b}")
    print(f"# {out['window']}: {len(out['lines'])} lines")
    for ln in out["lines"]:
        print(ln)
    return 0


def cmd_cloud(args):
    out = cloud.read(args.server, what=args.what, start=args.start, end=args.end, step=args.step, env_file=args.env_file)
    if args.json:
        print(json.dumps(out, indent=1))
        return 0
    s = out["server"]
    print(f"{s.get('name')}  {s.get('status')}" + (f"  {s.get('type')}  {s.get('location')}" if "type" in s else ""))
    if "ipv4" in s:
        print(f"  ipv4 {s['ipv4']} (blocked: {s['ipv4_blocked']})  private {', '.join(s['private']) or '-'}  backups {s['backup_window'] or 'off'}")
        for fw in s["firewalls"]:
            print(f"  firewall {fw.get('name') or fw.get('id')} ({fw.get('status')})" + (f": {fw['error']}" if fw.get("error") else ""))
            for r in fw.get("rules") or []:
                print(f"    {r}")
    for a in out.get("actions") or []:
        print(f"  action {a['started']}  {a['command']}  {a['status']}" + (f"  {a['error']}" if a.get("error") else ""))
    if "metrics" in out:
        m = out["metrics"]
        print(f"  graphs {m['start']} to {m['end']}, every {m['step_s']} s")
        for r in m["rows"]:
            print(f"    {r}")
    return 0


def parser():
    ap = argparse.ArgumentParser(prog="syboard", description="Syboard's node tools: assess a machine, install a node's stores, "
                                 "read a node's log, read its cloud server.")
    ap.add_argument("--version", action="version", version=f"syboard {__version__}")
    sub = ap.add_subparsers(dest="what", required=True)

    nd = sub.add_parser("node", help="a node's machine over SSH").add_subparsers(dest="verb", required=True)
    for verb, fn, helptext in (("plan", cmd_plan, "assess the machine and list the steps still to do (read only)"),
                               ("install", cmd_install, "install the node's stores; plans only, unless --apply is given")):
        p = nd.add_parser(verb, help=helptext)
        p.add_argument("host", help="the machine's address or host name")
        p.add_argument("--ssh-key", required=True, help="the private key that signs in to the machine")
        p.add_argument("--user", default="root", help="the user to sign in as (default root)")
        p.add_argument("--name", help="the node's name, used for its NATS server (default syboard-node)")
        p.add_argument("--requirements", help="a JSON file of requirements in place of the built-in ones")
        p.add_argument("--json", action="store_true", help="print JSON")
        if verb == "install":
            p.add_argument("--apply", action="store_true", help="make the changes (without it, nothing is changed)")
        p.set_defaults(fn=fn)
    j = nd.add_parser("journal", help="the machine's own log over a window (read only)")
    j.add_argument("host")
    j.add_argument("--ssh-key", required=True)
    j.add_argument("--user", default="root")
    j.add_argument("--since", required=True, help="UTC, such as 2026-01-31 08:30:00")
    j.add_argument("--until", required=True, help="UTC, such as 2026-01-31 09:00:00")
    j.add_argument("--grep", help="only the lines whose message matches this pattern")
    j.add_argument("--lines", default=200, type=int, help="the newest lines to show (1 to 2000, default 200)")
    j.add_argument("--json", action="store_true")
    j.set_defaults(fn=cmd_journal)

    c = sub.add_parser("cloud", help="a Hetzner Cloud server's status, firewalls, actions and graphs (read only)")
    c.add_argument("server", help="the server's name, or its public IPv4 address")
    c.add_argument("--what", default="all", choices=cloud.VIEWS)
    c.add_argument("--start", help="the graphs' start, UTC (default: an hour before --end)")
    c.add_argument("--end", help="the graphs' end, UTC (default: now)")
    c.add_argument("--step", default=300, type=int, help="seconds between graph points (default 300)")
    c.add_argument("--env-file", help="a .env file that holds HETZNER_API_KEY (default: the environment variable)")
    c.add_argument("--json", action="store_true")
    c.set_defaults(fn=cmd_cloud)
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return args.fn(args)
    except (node.NodeError, cloud.CloudError) as e:
        print(f"syboard: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
