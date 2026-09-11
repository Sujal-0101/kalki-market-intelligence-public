#!/usr/bin/env python3
"""Fail-closed privacy and packaging checks for a Kalki public source tree."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_PUBLIC_FILE_BYTES = 5 * 1024 * 1024
TEXT_SAMPLE_BYTES = MAX_PUBLIC_FILE_BYTES + 1

FORBIDDEN_DIRECTORY_NAMES = {
    ".agent",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "backups",
    "exports",
    "logs",
    "models",
    "private-research",
    "raw-data",
    "secrets",
    "supervisor-logs",
}
FORBIDDEN_SUFFIXES = {
    ".backup",
    ".bak",
    ".db",
    ".dump",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
}
FORBIDDEN_EXACT_PATHS = {
    "docs/PROGRESS.md",
    "docs/PRODUCTION_AUDIT_2026-08-27.md",
}


@dataclass(frozen=True)
class Finding:
    path: str
    category: str
    line: int | None = None

    def display(self) -> str:
        location = f"{self.path}:{self.line}" if self.line is not None else self.path
        return f"{location}: {self.category}"


CONTENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key header", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("AWS access-key shape", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("GitHub token shape", re.compile(r"\bgh[opsur]_[A-Za-z0-9]{30,}\b")),
    ("Slack token shape", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    (
        "live Discord webhook URL",
        re.compile(r"https://discord\.com/api/webhooks/\d{17,20}/[A-Za-z0-9._-]{20,}"),
    ),
    (
        "authorization header value",
        re.compile(
            r"(?im)^\s*authorization\s*[:=]\s*(?:basic|bearer)\s+[A-Za-z0-9._~+/=-]{12,}\s*$"
        ),
    ),
    ("credential-bearing URL", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@")),
    (
        "private operator home path",
        re.compile(r"/home/(?!YOUR_USER(?:/|\b)|ollama(?:/|\b))[a-z_][a-z0-9_-]*(?:/|\b)"),
    ),
    (
        "previous production hostname",
        re.compile(r"research\.kalkimarketingintelligence\.com", re.I),
    ),
    (
        "NVIDIA IR fixture URL",
        re.compile(r"investor\.nvidia\.com/news/press-release-details/2026/", re.I),
    ),
    (
        "removed NVIDIA fixture name",
        re.compile(r"nvidia-2026-(?:original-partnership|q2-partnership-recap)\.json", re.I),
    ),
)

DISCORD_LITERAL = re.compile(
    r"(?i)(?:discord|guild|channel|message|allowlist|user)[^\n]{0,100}"
    r"(?:[:=]\s*['\"]?|`)(\d{17,20})(?:['\"]|`|\b)"
)
EMAIL_ADDRESS = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@(?P<domain>[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)
PUBLIC_EMAIL_DOMAINS = {
    "apache.org",
    "example.com",
    "example.invalid",
    "postgresql.org",
    "python.org",
    "sec.gov",
    "users.noreply.github.com",
}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="public tree to inspect")
    parser.add_argument(
        "--allow-git-metadata",
        action="store_true",
        help="skip the new repository's .git directory after history isolation checks",
    )
    return parser.parse_args()


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _path_findings(path: Path, *, root: Path, allow_git: bool) -> list[Finding]:
    relative = _relative(path, root)
    parts = path.relative_to(root).parts
    findings: list[Finding] = []
    if ".git" in parts:
        if not allow_git:
            findings.append(Finding(relative, "Git metadata present before public initialization"))
        return findings
    if any(part in FORBIDDEN_DIRECTORY_NAMES for part in parts[:-1]):
        findings.append(Finding(relative, "forbidden private/runtime directory"))
    if relative in FORBIDDEN_EXACT_PATHS:
        findings.append(Finding(relative, "private engineering/production record"))
    name = path.name.casefold()
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        findings.append(Finding(relative, "environment file other than .env.example"))
    if any(name.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
        findings.append(Finding(relative, "sensitive/runtime file suffix"))
    if name.endswith((".dump.gz", ".sql.gz", ".sql.zst")):
        findings.append(Finding(relative, "database archive suffix"))
    if path.is_symlink():
        findings.append(Finding(relative, "symbolic links are not accepted in public export"))
    elif path.is_file() and path.stat().st_size > MAX_PUBLIC_FILE_BYTES:
        findings.append(Finding(relative, "file exceeds 5 MiB public-source limit"))
    return findings


def _content_findings(path: Path, *, root: Path) -> list[Finding]:
    relative = _relative(path, root)
    if not path.is_file() or path.is_symlink() or ".git" in path.relative_to(root).parts:
        return []
    raw = path.read_bytes()[:TEXT_SAMPLE_BYTES]
    if b"\x00" in raw:
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []
    findings: list[Finding] = []
    for category, pattern in CONTENT_RULES:
        for match in pattern.finditer(text):
            if category == "credential-bearing URL" and relative.startswith("tests/"):
                # Security tests intentionally contain rejected, obviously synthetic
                # user:password URL shapes. Gitleaks still scans all test content.
                continue
            findings.append(Finding(relative, category, text.count("\n", 0, match.start()) + 1))
    if not relative.startswith("tests/"):
        for match in DISCORD_LITERAL.finditer(text):
            findings.append(
                Finding(
                    relative,
                    "literal Discord snowflake outside synthetic tests",
                    text.count("\n", 0, match.start()) + 1,
                )
            )
    for match in EMAIL_ADDRESS.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        scheme_end = text.rfind("://", line_start, match.start())
        authority_prefix = text[scheme_end + 3 : match.start()] if scheme_end >= 0 else ""
        if (
            scheme_end >= 0
            and "/" not in authority_prefix
            and not any(character.isspace() for character in authority_prefix)
        ):
            # Credential-bearing URL tests are classified by their dedicated rule;
            # the user-info portion is not a contact email address.
            continue
        domain = match.group("domain").casefold()
        if domain in PUBLIC_EMAIL_DOMAINS or domain.endswith(
            (".apache.org", ".example", ".invalid", ".sec.gov", ".test")
        ):
            continue
        findings.append(
            Finding(
                relative,
                "email address outside official/reserved public domains",
                text.count("\n", 0, match.start()) + 1,
            )
        )
    return findings


def main() -> int:
    arguments = _arguments()
    root = arguments.root.resolve()
    if not root.is_dir():
        print("public-tree validation failed: root is not a directory", file=sys.stderr)
        return 2
    findings: list[Finding] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        if arguments.allow_git_metadata and current_path == root:
            directories[:] = [item for item in directories if item != ".git"]
        for directory in directories:
            findings.extend(
                _path_findings(
                    current_path / directory, root=root, allow_git=arguments.allow_git_metadata
                )
            )
        for filename in filenames:
            path = current_path / filename
            findings.extend(_path_findings(path, root=root, allow_git=arguments.allow_git_metadata))
            findings.extend(_content_findings(path, root=root))
    if findings:
        print(f"PUBLIC_TREE_VALIDATION=FAIL findings={len(findings)}", file=sys.stderr)
        for finding in findings[:50]:
            print(f"- {finding.display()}", file=sys.stderr)
        if len(findings) > 50:
            print(f"- {len(findings) - 50} additional finding(s) suppressed", file=sys.stderr)
        return 1
    file_count = sum(1 for item in root.rglob("*") if item.is_file() and ".git" not in item.parts)
    print(f"PUBLIC_TREE_VALIDATION=PASS files={file_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
