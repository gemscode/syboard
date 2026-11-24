# Copyright 2026 The Syboard Authors
# SPDX-License-Identifier: Apache-2.0
"""The leak scan: refuses key-shaped strings, private key blocks and committed .env files in the repository's files.

It prints where each finding is (file, line and the kind of finding), never the value it found. A maintainer can add a list of
private words to refuse, one per line, in a file named by SYBOARD_LEAKSCAN_DENY; that file stays outside the repository.
Usage: python scripts/leak_scan.py (exit 0 when nothing is found)."""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERNS = {
    "a private key block": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY"),
    "an AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "a GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "an Anthropic key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "an API key starting sk-": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    "a Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "a Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "a secret assigned in a literal": re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[=:]\s*['\"][A-Za-z0-9/+_.-]{20,}['\"]"),
}


def files():
    p = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard"], capture_output=True)
    if p.returncode == 0:
        return [f for f in p.stdout.decode().split("\0") if f]
    out = []
    for d, dirs, fs in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in (".git", "build", "dist", "__pycache__")]
        out += [os.path.relpath(os.path.join(d, f), ROOT) for f in fs]
    return out


def deny_words():
    path = os.environ.get("SYBOARD_LEAKSCAN_DENY")
    if not path:
        return []
    with open(path, encoding="utf-8") as f:
        return [w.strip() for w in f if w.strip() and not w.startswith("#")]


def main():
    deny = deny_words()
    findings = []
    for rel in files():
        name = os.path.basename(rel)
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            findings.append(f"{rel}: a committed .env file")
            continue
        try:
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                lines = f.readlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines, 1):
            for kind, rx in PATTERNS.items():
                if rx.search(line):
                    findings.append(f"{rel}:{i}: {kind}")
            low = line.lower()
            for w in deny:
                if w.lower() in low:
                    findings.append(f"{rel}:{i}: a private word from the deny list")
    for f in findings:
        print(f)
    print(f"leak scan: {len(findings)} finding(s) in {len(files())} files" + (f", with {len(deny)} private words" if deny else ""))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
