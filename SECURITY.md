# Security policy

Kalki is preparing a sanitized public release candidate. Until the repository owner
publishes and marks a version as supported, treat security reports as pre-release
reports.

## Reporting a vulnerability

Please use **GitHub private vulnerability reporting** for this repository when it is
enabled: open the repository's **Security** tab, choose **Advisories**, then
**Report a vulnerability**. Do not open a public issue for an unpatched vulnerability.

If private vulnerability reporting is not available, contact the repository owner
through a previously established private channel. No public security email address
has been designated, so this file intentionally does not invent or publish one.

Include, without real secrets or private research:

- affected commit/version and component;
- reproducible steps or a minimal proof of concept;
- expected and observed behavior;
- impact and required preconditions;
- suggested mitigation, if known.

Do not test against production, access other people's data, send Discord messages,
change DNS/tunnels/firewalls, attempt denial of service, publish dossiers, run
database migrations, or retain/exfiltrate sensitive data. Use local synthetic
fixtures and stop once the issue is demonstrated.

## Sensitive material

Never include credentials, tokens, cookies, private keys, database dumps, logs with
identifiers, private human research, Discord IDs/content, IP addresses, or raw model
responses in a report. State the secret type and affected location, redact the value,
and revoke it through the provider if exposure is suspected.

## Supported versions

No public supported-version promise exists yet. The accepted engineering baseline is
Observation Baseline V2 (Phase 45), but repository publication and support policy are
still owner decisions. Once releases exist, this table should be replaced with exact
supported tags and security-update windows.

## Security architecture

Read [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) for trust boundaries, public/
private separation, container hardening, model-output validation, database
immutability, and operator responsibilities.

## Disclosure process

The maintainer will aim to acknowledge a complete private report, reproduce it,
coordinate a fix and release, and credit the reporter if desired. No response-time
SLA is promised. Public disclosure should wait for maintainer coordination and a
reasonable remediation window.
