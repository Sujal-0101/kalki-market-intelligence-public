"""Observe private runtime resources and public responsiveness during a lab run."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

_CONTAINER_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_IEC_UNITS = {
    "B": 1,
    "KiB": 1_024,
    "MiB": 1_024**2,
    "GiB": 1_024**3,
    "TiB": 1_024**4,
}


class ResourceSample(BaseModel):
    """One content-free host/runtime/public observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    observed_at: datetime
    runtime_cpu_percent: float = Field(ge=0)
    runtime_memory_bytes: int = Field(ge=0)
    host_available_memory_bytes: int = Field(ge=0)
    host_swap_used_bytes: int = Field(ge=0)
    package_temperature_celsius: float | None = None
    public_status: int | None = None
    public_latency_seconds: float | None = None


def parse_iec_bytes(value: str) -> int:
    """Parse Docker's bounded IEC memory value."""

    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(B|KiB|MiB|GiB|TiB)", value.strip())
    if match is None:
        raise ValueError("unsupported Docker memory value")
    return round(float(match.group(1)) * _IEC_UNITS[match.group(2)])


def parse_meminfo(text: str) -> tuple[int, int]:
    """Return available memory and used swap from Linux meminfo."""

    values: dict[str, int] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([A-Za-z_()]+):\s+([0-9]+) kB", line)
        if match is not None:
            values[match.group(1)] = int(match.group(2)) * 1_024
    required = {"MemAvailable", "SwapTotal", "SwapFree"}
    if not required.issubset(values):
        raise ValueError("Linux meminfo omitted required counters")
    return values["MemAvailable"], values["SwapTotal"] - values["SwapFree"]


def parse_package_temperature(text: str) -> float | None:
    """Read the CPU package temperature without changing sensor state."""

    match = re.search(r"(?m)^Package id 0:\s+\+([0-9]+(?:\.[0-9]+)?)°C", text)
    return float(match.group(1)) if match is not None else None


def _run(arguments: list[str]) -> str:
    result = subprocess.run(  # noqa: S603 - fixed commands plus validated container names
        arguments,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout


def _client_running(container: str) -> bool:
    try:
        return _run(["docker", "inspect", "--format", "{{.State.Running}}", container]).strip() == (
            "true"
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _sample(runtime_container: str) -> ResourceSample:
    raw_stats = _run(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
            runtime_container,
        ]
    )
    stats: Any = json.loads(raw_stats)
    if not isinstance(stats, dict):
        raise ValueError("Docker stats did not return one object")
    cpu = str(stats.get("CPUPerc", "")).removesuffix("%")
    memory = str(stats.get("MemUsage", "")).split(" / ", 1)[0]
    available, swap_used = parse_meminfo(Path("/proc/meminfo").read_text(encoding="utf-8"))
    try:
        temperature = parse_package_temperature(_run(["sensors"]))
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        temperature = None
    started = time.monotonic()
    status: int | None = None
    try:
        request = Request(  # noqa: S310 - fixed loopback public origin
            "http://127.0.0.1:8001/radar",
            headers={"Host": "localhost"},
        )
        with urlopen(request, timeout=3) as response:  # noqa: S310
            response.read(1)
            status = response.status
    except OSError:
        pass
    latency = time.monotonic() - started
    return ResourceSample(
        observed_at=datetime.now(UTC),
        runtime_cpu_percent=float(cpu),
        runtime_memory_bytes=parse_iec_bytes(memory),
        host_available_memory_bytes=available,
        host_swap_used_bytes=swap_used,
        package_temperature_celsius=temperature,
        public_status=status,
        public_latency_seconds=latency if status is not None else None,
    )


def _summary(samples: list[ResourceSample]) -> dict[str, object]:
    if not samples:
        raise ValueError("resource observation requires at least one sample")
    temperatures = [
        item.package_temperature_celsius
        for item in samples
        if item.package_temperature_celsius is not None
    ]
    public_latencies = [
        item.public_latency_seconds for item in samples if item.public_latency_seconds is not None
    ]
    return {
        "samples": len(samples),
        "peak_runtime_cpu_percent": max(item.runtime_cpu_percent for item in samples),
        "peak_runtime_memory_bytes": max(item.runtime_memory_bytes for item in samples),
        "minimum_host_available_memory_bytes": min(
            item.host_available_memory_bytes for item in samples
        ),
        "starting_host_swap_used_bytes": samples[0].host_swap_used_bytes,
        "ending_host_swap_used_bytes": samples[-1].host_swap_used_bytes,
        "host_swap_growth_bytes": samples[-1].host_swap_used_bytes
        - samples[0].host_swap_used_bytes,
        "peak_package_temperature_celsius": max(temperatures) if temperatures else None,
        "public_successes": sum(item.public_status == 200 for item in samples),
        "public_failures": sum(item.public_status != 200 for item in samples),
        "public_latency_seconds_p50": (
            statistics.median(public_latencies) if public_latencies else None
        ),
        "public_latency_seconds_maximum": max(public_latencies) if public_latencies else None,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-container", required=True)
    parser.add_argument("--client-container", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        for name in (arguments.runtime_container, arguments.client_container):
            if _CONTAINER_NAME.fullmatch(name) is None:
                raise ValueError("container names must be bounded safe identifiers")
        if not 1 <= arguments.interval <= 60:
            raise ValueError("sample interval must be between 1 and 60 seconds")
        samples: list[ResourceSample] = []
        while _client_running(arguments.client_container):
            samples.append(_sample(arguments.runtime_container))
            time.sleep(arguments.interval)
        if not samples:
            raise ValueError("benchmark client was not running when observation began")
        report = {
            "schema_version": "1.0.0",
            "runtime_container": arguments.runtime_container,
            "client_container": arguments.client_container,
            "summary": _summary(samples),
            "samples": [item.model_dump(mode="json") for item in samples],
        }
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        with arguments.output.open("x", encoding="utf-8") as target:
            json.dump(report, target, indent=2)
            target.write("\n")
        print(json.dumps(report["summary"], indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"resource observation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
