---
version: 0.2.0
updated: 2026-11-27
---

# Troubleshooting

Version 0.2.0 · Updated November 27, 2026

`syboard` prints the reason for every error on standard error, starting with `syboard:`, and exits with `1`. This page lists the
errors you are most likely to see and how to fix them.

## Installation

**macOS says the executable "cannot be opened" or "is damaged".** The browser marked the download as quarantined, and the
executable is not signed yet. Clear the mark: `xattr -d com.apple.quarantine ~/Downloads/syboard-macos-arm64`.

**`shasum -c` reports `FAILED`.** The download is incomplete or altered. Download the executable and its `.sha256` file again.

## Signing in to the machine

**`syboard: no SSH key at <path>`.** The file given with `--ssh-key` doesn't exist. Give the private key's full path, for example
`~/.ssh/my-node`.

**`syboard: the machine did not answer over SSH (exit <n>)`.** Check that the machine is up, that its address is right, that the
key is the one the machine accepts for the user (`root` by default, `--user` otherwise), and that port 22 is open to you. Then run
`syboard cloud` to see the server's status from the provider's side.

## Assessing and installing

**`refused: below the minimum for <requirements>; nothing was changed`.** The machine is below a minimum, for example fewer than
4 vCPU or not Debian 13. Resize or reinstall the machine, or pass your own requirements with `--requirements` for a test machine.

**`ports` shows `in use: ...`.** Another program holds one of the stores' local ports (4222, 8222, 9302, 5434 or 6379). Stop it,
or use a machine without it.

**`outbound` shows `unreachable: ...`.** The machine cannot reach the hosts listed over HTTPS, or port 7844. Open outbound HTTPS in
the machine's firewall and its provider's firewall.

**`step <name> failed: ...`.** The step's last output is shown. Fix the cause and run the same `node install --apply` again: the
steps already done are skipped, and the install resumes at the failed step.

**`--name is lower-case letters, digits and dashes, 1 to 63 of them`.** Choose a name such as `node-1`.

## Verifying

**The run is refused because `stores/node.env` does not name the node.** You gave a `--name` that differs from the name the node
was installed with, or the machine is not a node yet. Use the same name as `node install`, or install the node first.

**A `running` level fails after a restart.** A container restarted since the last verify. If the restart was expected, run
`node verify` again: the new run becomes the baseline.

**`syboard: the records were not written to <file>`.** The report was printed, but `~/.syboard/deployments/` isn't writable. Fix
the folder's permissions.

## Reading the cloud server

**`HETZNER_API_KEY is not set in <where>`.** Export the token, or name the `.env` file that holds it with `--env-file`.

**`no server named <name> in the token's project`.** The token belongs to another project, or the name is wrong. Give the server's
public IPv4 address instead.

**`--step is 10 to 86400 seconds` or `--start must come before --end`.** Fix the graph window's options.

## Still stuck?

Ask the documentation chat at [sideborg.app/documentation/chat](https://sideborg.app/documentation/chat), or open an issue at
[github.com/gemscode/syboard/issues](https://github.com/gemscode/syboard/issues) with the command you ran and its output.
