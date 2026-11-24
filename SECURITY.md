# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately through this repository's
**Security** tab, **Report a vulnerability**. You receive an answer within a few days, and the fix is
published with a security advisory once a release carries it.

## Supported versions

Security fixes go into the latest release.

## How the harness treats secrets

- Keys and tokens are read by their names from a local `.env` file and sent only in request headers;
  they are never printed, logged or written into the repository.
- The cloud reads send only GET requests and do not follow redirects.
- Every administrative command passes the node's governance check before it acts.
