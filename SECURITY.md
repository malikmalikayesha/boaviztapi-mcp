# Security policy

## Supported versions

Security fixes go into the latest release only.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub: open the repository's
**Security** tab and choose **Report a vulnerability**. Do not open a public issue.

You can expect a first reply within a week. Once a fix is released, the advisory is
published with credit to the reporter unless you prefer otherwise.

## Scope

This server is a read-only client for BoaviztAPI over stdio. It holds no secrets,
stores nothing on disk and only sends requests to the configured `BOAVIZTAPI_URL`.
Problems in BoaviztAPI itself should be reported to
[Boavizta](https://github.com/Boavizta/boaviztapi/security).
