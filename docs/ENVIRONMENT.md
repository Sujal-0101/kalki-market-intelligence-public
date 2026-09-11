# Phase 0 Environment Report

## Inspection context

- **Observed:** 2026-08-20 at approximately 20:27 EDT (America/Toronto, UTC-04:00)
- **Method:** safe, read-only commands from a restricted Codex execution session
- **Scope:** no packages, services, containers, disks, mounts, network settings, Git configuration, or external resources were changed

Sensitive identifiers are intentionally omitted, including the local username, IP and MAC addresses, disk serials, filesystem UUIDs, and account information.

## Verified system facts

| Area | Observation |
|---|---|
| Operating system | Ubuntu 26.04 LTS (Resolute Raccoon), x86-64 |
| Kernel | Linux 7.0.0-30-generic |
| CPU | Intel Core i7-8550U at 1.80 GHz; 1 socket, 4 physical cores, 2 threads/core, 8 logical CPUs online |
| Memory | 22 GiB total; about 19 GiB available at inspection time |
| Swap | 8.0 GiB configured; unused at inspection time |
| Integrated GPU | Intel UHD Graphics 620; `i915` kernel driver in use |
| Discrete GPU | NVIDIA GeForce 940MX; `nvidia` kernel driver selected and module loaded |
| Session user | Non-root; not a member of the checked `sudo`, `adm`, `docker`, `systemd-journal`, `video`, or `render` groups |
| Init/service tooling | `systemctl` is installed and `/run/systemd/system` exists, indicating a systemd-based host; this restricted session is not the host PID 1 and cannot access the system service bus |

The NVIDIA device is present, but `nvidia-smi` could not communicate with the driver. This does not establish whether the problem is host configuration, device support, or isolation imposed by the execution session. No driver or CUDA change was attempted, and no assumption should be made that this GPU will help local-model inference.

## Storage layout

| Device | Observed size/type | Filesystem and use |
|---|---|---|
| System disk | 232.9 GiB NVMe | 1 GiB FAT EFI partition and 231.8 GiB ext4 root partition; about 192 GiB available on `/` |
| Secondary disk | 931.5 GiB SATA | One 931.5 GiB ext4 partition; no mount point visible in this session |

Available capacity for the secondary filesystem cannot be reported while it is unmounted. It was not formatted, mounted, repartitioned, erased, or otherwise modified. No storage-layout change is proposed in Phase 0.

## Development tools

| Tool | Status |
|---|---|
| Git | Installed: 2.53.0 |
| Python | Installed: CPython 3.14.4 as `python3`; system Python was not modified |
| Docker Engine CLI | Installed: 29.7.2 |
| Docker Compose | Installed as the Docker CLI plugin: v5.5.0 |
| Codex CLI | Installed: 0.149.0; version lookup emitted a harmless warning because the restricted filesystem prevented PATH-alias creation |
| Ollama | Not installed / not available on `PATH`, as expected |
| Node.js | Not installed / not available on `PATH` |
| npm | Not installed / not available on `PATH` |

## Docker state

The Docker Unix socket exists, but the session user cannot read or write it and is not in the `docker` group. Consequently:

- Docker Engine and Compose client versions were verified.
- Docker daemon/server version and runtime state were not verified.
- The Docker service's active/enabled state was not observable because the system service bus is inaccessible.
- The reported earlier `hello-world` success could not be independently verified without daemon access. No image was pulled and no container was created or run.

These are inspection limitations, not evidence that Docker is broken.

## Local networking

Basic interface and route queries were attempted without elevated privileges. The restricted execution session denied access to network state, so interface state and default routing could not be verified. No addresses, routes, DNS settings, firewall rules, or network configuration were changed, and no external website was contacted.

## Repository state at inspection

- Working directory is the `kalki-market-intelligence` repository.
- Branch is `main` with no commits yet.
- Before Phase 0 documentation was written, the only visible project file was an empty, untracked `README.md`; empty `docs/`, `.agents/`, and `.codex/` directories were present.
- No pre-existing `AGENTS.md` was found.
- At Phase 0 completion, the seven requested files are untracked: `.gitignore`, `AGENTS.md`, `ARCHITECTURE.md`, `README.md`, `ROADMAP.md`, `docs/ENVIRONMENT.md`, and `docs/PROJECT_SPEC.md`.
- No commit was created.

## Expected versus observed

The expected Ubuntu release, CPU model and topology, approximate RAM and swap, system and secondary disk sizes/types, NVIDIA GeForce 940MX, Intel integrated graphics, Git, Python, Docker CLI, Docker Compose, Codex, and absent Ollama were all observed.

Differences or unresolved points:

- Node.js and npm were confirmed absent; their status had previously been unknown.
- The NVIDIA hardware and module were detected, but `nvidia-smi` was not operational in this session.
- Docker's daemon/service state and prior `hello-world` result were not independently verifiable due to permissions.
- systemd appears present on the host, but service status is unavailable inside the restricted session.
- local interface and routing state could not be read inside the restricted session.

## Recommended minimum next setup

The next milestone should be **Phase 1: repository foundations, schemas, tests, and local development structure**, after the user reviews and approves the Phase 0 documentation. Phase 1 should select the minimal stack, keep dependencies isolated, define evidence/time/schema invariants, and establish repeatable local checks. It should not install Ollama, expose services, use the secondary disk, or create paid/external resources; those require their own later approvals and phases.
