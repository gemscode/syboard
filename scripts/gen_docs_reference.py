# Copyright 2026 The Syboard Authors
# SPDX-License-Identifier: Apache-2.0
"""Writes the documentation's generated pages from the code, so they never drift from it: docs/reference/cli.md from the syboard
command's own argument parser, docs/reference/requirements.md from resources.REQUIREMENTS and resources.CHECKLIST, and
docs/release-notes.md from CHANGELOG.md.

Run from the repository root: python3 scripts/gen_docs_reference.py [--check]. With --check it exits 1 when a page differs from
what the code gives (CI can run it)."""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from syboard import __version__, resources  # noqa: E402
from syboard.cli import parser  # noqa: E402

OUT = os.path.join(ROOT, "docs", "reference", "cli.md")
REQ_OUT = os.path.join(ROOT, "docs", "reference", "requirements.md")
NOTES_OUT = os.path.join(ROOT, "docs", "release-notes.md")
EXAMPLES = {
    "node plan": "syboard node plan 203.0.113.10 --ssh-key ~/.ssh/my-node",
    "node install": "syboard node install 203.0.113.10 --ssh-key ~/.ssh/my-node --name node-1 --apply",
    "node verify": "syboard node verify 203.0.113.10 --ssh-key ~/.ssh/my-node --name node-1",
    "node journal": 'syboard node journal 203.0.113.10 --ssh-key ~/.ssh/my-node --since "2026-01-31 08:50:00" --until "2026-01-31 09:10:00"',
    "cloud": "syboard cloud node-1 --what server",
}


def subparsers(p):
    for a in p._actions:
        if isinstance(a, argparse._SubParsersAction):
            helps = {c.dest: c.help for c in a._choices_actions}
            for name, sp in a.choices.items():
                yield name, sp, helps.get(name, "")


def commands():
    out = []
    for name, sp, h in subparsers(parser()):
        inner = list(subparsers(sp))
        if inner:
            for verb, vp, vh in inner:
                out.append((f"{name} {verb}", vp, vh))
        else:
            out.append((name, sp, h))
    return out


def flag_rows(p):
    rows = []
    for a in p._actions:
        if isinstance(a, (argparse._HelpAction, argparse._SubParsersAction)):
            continue
        if a.option_strings:
            name = ", ".join(a.option_strings) + ("" if a.nargs == 0 else f" <{a.dest.replace('_', '-')}>")
        else:
            name = f"<{a.dest}>"
        what = (a.help or "").rstrip(".")
        if a.choices:
            what += ("; " if what else "") + "one of " + ", ".join(f"`{c}`" for c in a.choices)
        default = "" if a.default in (None, False, argparse.SUPPRESS) or a.nargs == 0 else f"`{a.default}`"
        req = "yes" if (a.required or not a.option_strings) else ""
        rows.append(f"| `{name}` | {what} | {req} | {default} |")
    return rows


def page():
    cmds = commands()
    lines = ["---", f"version: {__version__}", "---", "", "# CLI reference", "",
             f"Version {__version__} · Generated from the `syboard` command's own parser by `scripts/gen_docs_reference.py`.", "",
             "The `syboard` command has two command groups: `node` works on a node's machine over SSH, and `cloud` reads a Hetzner Cloud "
             "server. Every command prints text, or JSON with `--json`. `syboard --version` prints the version, and `syboard <command> "
             "--help` prints a command's help.", "",
             "## Commands", "", "| Command | Description | Example |", "|---|---|---|"]
    for name, _, h in cmds:
        lines.append(f"| `syboard {name}` | {h[:1].upper() + h[1:] if h else ''} | `{EXAMPLES.get(name, 'syboard ' + name)}` |")
    lines += ["", "## Options of each command", ""]
    for name, p, h in cmds:
        lines += [f"### syboard {name}", "", (h[:1].upper() + h[1:] + ".") if h else "", "", "```", p.format_usage().strip(), "```", "",
                  "| Option | Description | Required | Default |", "|---|---|---|---|"] + flag_rows(p) + [""]
    lines += ["## Exit codes", "", "| Code | Meaning |", "|---|---|",
              "| `0` | The command did what it was asked: the plan was shown, every install step is done, every check passed, or the log or "
              "server was read. |",
              "| `1` | The command was refused or failed: a missing SSH key, an invalid name, a machine below the minimum, a check that did "
              "not pass, a machine that did not answer, or records that could not be written. The reason is printed on standard error. |",
              "| `2` | The command line itself was wrong: an unknown command or a missing required option. |",
              "| `130` | Interrupted with Ctrl-C. |", "",
              "## Environment", "", "| Variable | Used by | What it holds |", "|---|---|---|",
              "| `HETZNER_API_KEY` | `syboard cloud` | The Hetzner Cloud API token, read from the environment or from the file "
              "`--env-file` names. It is sent only to Hetzner's API address. |", "",
              "## Files", "", "| Path | Written by | What it holds |", "|---|---|---|",
              "| `~/.syboard/deployments/<host>.jsonl` | `node install --apply`, `node verify` | One JSON record per install step and per "
              "verified module, with a summary per full verify run. The next `node verify` reads the containers' restart counts from it. |", ""]
    return "\n".join(lines)


def cell(v):
    return str(v).replace("|", "\\|") if v not in (None, "") else ""


def requirements_page():
    lines = ["---", f"version: {__version__}", "---", "", "# Node requirements and checklist", "",
             f"Version {__version__} · Generated from `src/syboard/resources.py` by `scripts/gen_docs_reference.py`.", "",
             "## Requirements", "",
             "`syboard node plan` measures a machine against these requirements, and `syboard node install` refuses a machine below any "
             "minimum. A JSON file of the same shape replaces them with `--requirements`.", "",
             "| Requirement | Minimum | Recommended | Why |", "|---|---|---|---|"]
    for r in resources.REQUIREMENTS:
        unit = f" {r['unit']}" if r.get("unit") else ""
        rec = f"{r['recommended']}{unit}" if r.get("recommended") is not None else ""
        lines.append(f"| {cell(r['what'])} (`{r['id']}`) | {cell(str(r['minimum']) + unit)} | {cell(rec)} | {cell(r['why'])} |")
    cl = resources.CHECKLIST
    lines += ["", "## Checklist", "",
              f"`syboard node verify` checks each module of the checklist (version {cl.get('version')}) at three levels. A JSON file of the "
              "same shape replaces it with `--checklist`.", "", "| Level | What passes |", "|---|---|"]
    for level, what in cl["levels"].items():
        lines.append(f"| {level} | {cell(what)} |")
    lines += ["", "| Module | What it is | Present | Running | Working | Fix when it fails |", "|---|---|---|---|---|---|"]
    for m in cl["modules"]:
        chk = lambda k: ", ".join(f"`{x}`" for x in m.get(k) or []) or ""  # noqa: E731
        lines.append(f"| `{m['id']}` | {cell(m['name'])} | {chk('present')} | {chk('running')} | {chk('working')} | {cell(m.get('fix'))} |")
    lines += ["", "One more row, `coverage`, checks that every container on the machine belongs to a module.", "",
              "### Not checked", "", "| What | Why |", "|---|---|"]
    for n in cl.get("not_checked") or []:
        lines.append(f"| {cell(n['what'])} | {cell(n['why'])} |")
    return "\n".join(lines) + "\n"


def notes_page():
    text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    body = text.split("\n", 1)[1] if text.startswith("# ") else text
    return "\n".join(["---", f"version: {__version__}", "---", "", "# Release notes", "",
                      "Copied from `CHANGELOG.md` by `scripts/gen_docs_reference.py`.", ""]) + body


if __name__ == "__main__":
    pages = {OUT: page(), REQ_OUT: requirements_page(), NOTES_OUT: notes_page()}
    if "--check" in sys.argv:
        stale = [p for p, text in pages.items() if not os.path.exists(p) or open(p, encoding="utf-8").read() != text]
        print("the generated pages are up to date" if not stale else
              "differs from the code: " + ", ".join(os.path.relpath(p, ROOT) for p in stale) + " (run scripts/gen_docs_reference.py)")
        sys.exit(1 if stale else 0)
    for p, text in pages.items():
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        print(os.path.relpath(p, ROOT))
