"""Tests for content-free model-serving resource observations."""

from kalki_market_intelligence.benchmarking.resource_observation import (
    parse_iec_bytes,
    parse_meminfo,
    parse_package_temperature,
)


def test_docker_memory_units_are_parsed_deterministically() -> None:
    assert parse_iec_bytes("2.35GiB") == round(2.35 * 1_024**3)
    assert parse_iec_bytes("64MiB") == 64 * 1_024**2


def test_meminfo_returns_available_memory_and_used_swap() -> None:
    available, swap_used = parse_meminfo(
        "MemTotal:       1000000 kB\n"
        "MemAvailable:    500000 kB\n"
        "SwapTotal:       200000 kB\n"
        "SwapFree:        150000 kB\n"
    )

    assert available == 500_000 * 1_024
    assert swap_used == 50_000 * 1_024


def test_temperature_is_optional_and_bounded_to_package_sensor() -> None:
    assert parse_package_temperature("Package id 0:  +87.0°C  (high = +100.0°C)") == 87.0
    assert parse_package_temperature("GPU: +40.0°C") is None
