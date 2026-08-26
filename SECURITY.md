# Security policy

paperflow is a portfolio pipeline with **no auth by design** — anyone who can reach
the web UI can read and modify its ledger. See [Non-goals](README.md#non-goals) in
the README. Do not expose a public deployment to untrusted users without putting
access controls in front of it at the host level.

## Supported versions

Only the latest commit on `main` is supported. There are no release branches.

## Reporting a vulnerability

Please open a [private security advisory](https://github.com/lordbasilaiassistant-sudo/paperflow/security/advisories/new)
rather than a public issue, or email **eli@broke2builtai.com**.

You'll get an acknowledgment within a few days and a fix (or an honest "won't fix,
here's why") as soon as the diagnosis is done.
