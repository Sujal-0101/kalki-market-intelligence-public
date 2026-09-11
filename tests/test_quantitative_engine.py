"""Reference-value and safety tests for deterministic calculations."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from kalki_market_intelligence.contracts.domain import CurrencyCode
from kalki_market_intelligence.providers.market_data.contracts import (
    BarRequest,
    BarSeries,
    DailyBar,
    FreshnessStatus,
    PriceAdjustment,
    QualityMetadata,
    VolumeAdjustment,
)
from kalki_market_intelligence.quantitative import algorithms
from kalki_market_intelligence.quantitative.contracts import (
    CALCULATION_VERSION,
    FinancialFact,
    FinancialPeriodKind,
    FinancialUnit,
    MetricResult,
)
from kalki_market_intelligence.quantitative.engine import QuantitativeEngine

FIXTURE_PATH = Path(__file__).parents[1] / "data/fixtures/quantitative/reference-cases.json"
REFERENCE = cast(dict[str, object], json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
ENGINE = QuantitativeEngine()
INSTRUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BENCHMARK_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ISSUER_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
START = date(2026, 1, 1)
FINANCIAL_CUTOFF = datetime(2026, 3, 1, tzinfo=UTC)


def decimals(name: str) -> tuple[Decimal, ...]:
    return tuple(Decimal(value) for value in cast(list[str], REFERENCE[name]))


def nested(name: str) -> dict[str, object]:
    return cast(dict[str, object], REFERENCE[name])


def make_series(
    closes: tuple[Decimal, ...],
    *,
    instrument_id: UUID = INSTRUMENT_ID,
    highs: tuple[Decimal, ...] | None = None,
    lows: tuple[Decimal, ...] | None = None,
    volumes: tuple[int, ...] | None = None,
    currency: CurrencyCode = CurrencyCode.US_DOLLAR,
    adjustment: PriceAdjustment = PriceAdjustment.SPLIT_ADJUSTED,
    volume_adjustment: VolumeAdjustment = VolumeAdjustment.SPLIT_ADJUSTED,
    freshness: FreshnessStatus = FreshnessStatus.CURRENT,
) -> BarSeries:
    highs = highs or tuple(value + 1 for value in closes)
    lows = lows or tuple(max(value - 1, value / 2) for value in closes)
    volumes = volumes or tuple(100 * (index + 1) for index in range(len(closes)))
    assert len(highs) == len(lows) == len(volumes) == len(closes)
    bars: list[DailyBar] = []
    for index, close in enumerate(closes):
        session = START + timedelta(days=index)
        available = datetime.combine(session, time(20), tzinfo=UTC)
        bars.append(
            DailyBar(
                instrument_id=instrument_id,
                session_date=session,
                open=close,
                high=highs[index],
                low=lows[index],
                close=close,
                volume=volumes[index],
                currency=currency,
                adjustment=adjustment,
                volume_adjustment=volume_adjustment,
                available_at=available,
                retrieved_at=available + timedelta(minutes=1),
                source_record_id=f"synthetic-{instrument_id}-{index}",
                source_content_sha256=f"{index + 1:064x}",
            )
        )
    cutoff = bars[-1].retrieved_at + timedelta(hours=1)
    request = BarRequest(
        instrument_id=instrument_id,
        start_date=bars[0].session_date,
        end_date=bars[-1].session_date,
        currency=currency,
        adjustment=adjustment,
        volume_adjustment=volume_adjustment,
        knowledge_cutoff_at=cutoff,
        freshness_max_age_seconds=86_400,
    )
    return BarSeries(
        request=request,
        bars=tuple(bars),
        quality=QualityMetadata(
            provider_name="synthetic-quantitative-reference",
            license_reference="project-generated synthetic fixture",
            evaluated_at=cutoff,
            freshness_status=freshness,
            row_count=len(bars),
            coverage_start=bars[0].session_date,
            coverage_end=bars[-1].session_date,
            latest_available_at=bars[-1].available_at,
            issues=(),
        ),
    )


def fact(
    concept: str,
    value: str,
    *,
    period_end: date = date(2025, 12, 31),
    period_start: date | None = None,
    period_kind: FinancialPeriodKind = FinancialPeriodKind.INSTANT,
    unit: FinancialUnit = FinancialUnit.CURRENCY,
    currency: CurrencyCode | None = CurrencyCode.US_DOLLAR,
    issuer_id: UUID = ISSUER_ID,
    available_at: datetime = datetime(2026, 2, 15, tzinfo=UTC),
) -> FinancialFact:
    return FinancialFact(
        fact_id=f"{concept}-{period_end}-{value}",
        issuer_id=issuer_id,
        concept=concept,
        value=Decimal(value),
        unit=unit,
        currency=currency,
        period_kind=period_kind,
        period_start=period_start,
        period_end=period_end,
        available_at=available_at,
        retrieved_at=available_at + timedelta(minutes=1),
        source_record_id=f"synthetic-{concept}",
        source_content_sha256="a" * 64,
    )


def values(result: MetricResult, component: str = "value") -> tuple[Decimal, ...]:
    return tuple(point.value for point in result.points if point.component == component)


def assert_close(actual: tuple[Decimal, ...], expected: tuple[Decimal, ...]) -> None:
    tolerance = Decimal(cast(str, REFERENCE["decimal_tolerance"]))
    assert len(actual) == len(expected)
    assert all(abs(left - right) <= tolerance for left, right in zip(actual, expected, strict=True))


def test_reference_fixture_is_explicitly_synthetic() -> None:
    assert REFERENCE["schema_version"] == "1"
    assert "not market evidence" in cast(str, REFERENCE["description"])


def test_sma_and_ema_match_exact_reference_values() -> None:
    closes = decimals("linear_closes")

    assert tuple(value for _, value in algorithms.rolling_sma(closes, 3)) == decimals(
        "sma_period_3"
    )
    assert tuple(value for _, value in algorithms.ema(closes, 3)) == decimals("ema_period_3")
    assert values(ENGINE.simple_moving_average(make_series(closes), period=3)) == decimals(
        "sma_period_3"
    )
    assert values(ENGINE.exponential_moving_average(make_series(closes), period=3)) == decimals(
        "ema_period_3"
    )


def test_algorithm_precision_is_independent_of_callers_decimal_context() -> None:
    closes = decimals("linear_closes")
    expected = algorithms.macd(closes, 2, 3, 2)

    with localcontext() as context:
        context.prec = 8
        actual = algorithms.macd(closes, 2, 3, 2)

    assert actual == expected

    series = make_series((Decimal("3"), Decimal("7")))
    expected_result = ENGINE.cumulative_return(series)
    with localcontext() as context:
        context.prec = 4
        actual_result = ENGINE.cumulative_return(series)
    assert actual_result == expected_result


def test_rsi_matches_wilder_reference_values() -> None:
    result = ENGINE.relative_strength_index(make_series(decimals("linear_closes")), period=3)

    assert values(result) == decimals("rsi_period_3")
    assert result.unit == "index_0_100"


def test_macd_matches_exact_linear_reference_values() -> None:
    result = ENGINE.macd(
        make_series(decimals("linear_closes")), fast_period=2, slow_period=3, signal_period=2
    )
    expected = cast(list[dict[str, str]], REFERENCE["macd_2_3_2"])

    assert_close(values(result, "line"), tuple(Decimal(item["line"]) for item in expected))
    assert_close(values(result, "signal"), tuple(Decimal(item["signal"]) for item in expected))
    assert_close(
        values(result, "histogram"),
        tuple(Decimal(item["histogram"]) for item in expected),
    )


def test_atr_matches_wilder_reference_values() -> None:
    case = nested("atr")
    closes = tuple(Decimal(value) for value in cast(list[str], case["closes"]))
    highs = tuple(Decimal(value) for value in cast(list[str], case["highs"]))
    lows = tuple(Decimal(value) for value in cast(list[str], case["lows"]))
    result = ENGINE.average_true_range(
        make_series(closes, highs=highs, lows=lows), period=cast(int, case["period"])
    )

    assert values(result) == tuple(Decimal(value) for value in cast(list[str], case["expected"]))


def test_volatility_uses_sample_deviation_and_declared_annualization() -> None:
    case = nested("volatility")
    closes = tuple(Decimal(value) for value in cast(list[str], case["closes"]))
    result = ENGINE.annualized_volatility(
        make_series(closes), periods_per_year=cast(int, case["periods_per_year"])
    )

    assert values(result) == (Decimal(cast(str, case["expected"])),)
    assert {parameter.name: parameter.value for parameter in result.parameters} == {
        "return_type": "simple",
        "sample_denominator": "n-1",
        "periods_per_year": "100",
    }


def test_return_volume_position_and_drawdown_reference_values() -> None:
    volume_case = nested("relative_volume")
    volume_series = make_series(
        (Decimal(10), Decimal(11), Decimal(12)),
        volumes=tuple(cast(list[int], volume_case["volumes"])),
    )
    position_case = nested("range_position")
    drawdown_case = nested("maximum_drawdown")

    assert values(
        ENGINE.relative_volume(
            volume_series, comparison_period=cast(int, volume_case["comparison_period"])
        )
    ) == (Decimal(cast(str, volume_case["expected"])),)
    assert values(
        ENGINE.fifty_two_week_position(
            make_series(
                tuple(Decimal(value) for value in cast(list[str], position_case["closes"]))
            ),
            lookback_sessions=4,
        )
    ) == (Decimal(cast(str, position_case["expected"])),)
    assert values(
        ENGINE.maximum_drawdown(
            make_series(tuple(Decimal(value) for value in cast(list[str], drawdown_case["closes"])))
        )
    ) == (Decimal(cast(str, drawdown_case["expected"])),)


def test_benchmark_beta_and_relative_return_match_reference() -> None:
    case = nested("benchmark")
    asset = make_series(tuple(Decimal(value) for value in cast(list[str], case["asset_closes"])))
    benchmark = make_series(
        tuple(Decimal(value) for value in cast(list[str], case["benchmark_closes"])),
        instrument_id=BENCHMARK_ID,
    )

    assert values(ENGINE.beta(asset, benchmark)) == (Decimal(cast(str, case["beta"])),)
    assert values(ENGINE.benchmark_relative_return(asset, benchmark)) == (
        Decimal(cast(str, case["relative_return"])),
    )


def test_every_consumed_bar_and_value_is_preserved_in_lineage() -> None:
    series = make_series(decimals("linear_closes"))
    result = ENGINE.simple_moving_average(series, period=3)

    assert result.implementation_version == CALCULATION_VERSION
    assert len(result.inputs) == len(series.bars)
    assert [item.values[0].value for item in result.inputs] == [bar.close for bar in series.bars]
    assert [item.source_content_sha256 for item in result.inputs] == [
        bar.source_content_sha256 for bar in series.bars
    ]
    assert {item.subject_id for item in result.inputs} == {INSTRUMENT_ID}
    assert all(item.price_adjustment is PriceAdjustment.SPLIT_ADJUSTED for item in result.inputs)


def test_stale_prices_fail_closed() -> None:
    with pytest.raises(ValueError, match="current"):
        ENGINE.cumulative_return(
            make_series((Decimal(1), Decimal(2)), freshness=FreshnessStatus.STALE)
        )


def test_unadjusted_prices_fail_closed() -> None:
    with pytest.raises(ValueError, match="split-adjusted"):
        ENGINE.cumulative_return(
            make_series((Decimal(1), Decimal(2)), adjustment=PriceAdjustment.UNADJUSTED)
        )


def test_unadjusted_volume_and_zero_comparison_fail_closed() -> None:
    with pytest.raises(ValueError, match="split-adjusted volume"):
        ENGINE.relative_volume(
            make_series(
                (Decimal(1), Decimal(2), Decimal(3)),
                volume_adjustment=VolumeAdjustment.UNADJUSTED,
            ),
            comparison_period=2,
        )
    with pytest.raises(ValueError, match="zero"):
        ENGINE.relative_volume(
            make_series((Decimal(1), Decimal(2), Decimal(3)), volumes=(0, 0, 10)),
            comparison_period=2,
        )


def test_missing_values_and_flat_ranges_fail_instead_of_guessing() -> None:
    with pytest.raises(ValueError, match="at least 3"):
        ENGINE.simple_moving_average(make_series((Decimal(1), Decimal(2))), period=3)
    with pytest.raises(ValueError, match="flat"):
        ENGINE.fifty_two_week_position(
            make_series((Decimal(2), Decimal(2), Decimal(2))), lookback_sessions=3
        )


def test_benchmark_mismatches_and_zero_variance_fail_closed() -> None:
    asset = make_series((Decimal(10), Decimal(11), Decimal(12)))
    canadian = make_series(
        (Decimal(10), Decimal(11), Decimal(12)),
        instrument_id=BENCHMARK_ID,
        currency=CurrencyCode.CANADIAN_DOLLAR,
    )
    flat = make_series((Decimal(10), Decimal(10), Decimal(10)), instrument_id=BENCHMARK_ID)

    with pytest.raises(ValueError, match="currencies"):
        ENGINE.beta(asset, canadian)
    with pytest.raises(ValueError, match="zero variance"):
        ENGINE.beta(asset, flat)


def test_current_debt_and_margin_ratios_match_exact_values() -> None:
    assets = fact("CurrentAssets", "200")
    liabilities = fact("CurrentLiabilities", "100")
    debt = fact("Debt", "50")
    equity = fact("Equity", "100")
    revenue = fact(
        "Revenue",
        "400",
        period_kind=FinancialPeriodKind.DURATION,
        period_start=date(2025, 1, 1),
    )
    gross_profit = fact(
        "GrossProfit",
        "160",
        period_kind=FinancialPeriodKind.DURATION,
        period_start=date(2025, 1, 1),
    )

    assert values(ENGINE.current_ratio(assets, liabilities, cutoff_at=FINANCIAL_CUTOFF)) == (
        Decimal("2"),
    )
    assert values(ENGINE.debt_to_equity_ratio(debt, equity, cutoff_at=FINANCIAL_CUTOFF)) == (
        Decimal("0.5"),
    )
    assert values(ENGINE.gross_margin(gross_profit, revenue, cutoff_at=FINANCIAL_CUTOFF)) == (
        Decimal("0.4"),
    )


def test_return_on_equity_uses_period_boundary_average() -> None:
    income = fact(
        "NetIncome",
        "30",
        period_kind=FinancialPeriodKind.DURATION,
        period_start=date(2025, 1, 1),
    )
    beginning = fact("Equity", "100", period_end=date(2025, 1, 1))
    ending = fact("Equity", "140")

    result = ENGINE.return_on_equity(income, beginning, ending, cutoff_at=FINANCIAL_CUTOFF)

    assert values(result) == (Decimal("0.25"),)
    assert len(result.inputs) == 3


def test_growth_cagr_and_valuation_ratios_match_exact_values() -> None:
    cagr_prior = fact(
        "Revenue",
        "100",
        period_start=date(2023, 1, 1),
        period_end=date(2023, 12, 31),
        period_kind=FinancialPeriodKind.DURATION,
    )
    growth_prior = fact(
        "Revenue",
        "100",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
        period_kind=FinancialPeriodKind.DURATION,
    )
    current = fact(
        "Revenue",
        "121",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        period_kind=FinancialPeriodKind.DURATION,
    )
    market_cap = fact("MarketCapitalization", "1000")
    earnings = fact(
        "NetIncome",
        "100",
        period_start=date(2025, 1, 1),
        period_kind=FinancialPeriodKind.DURATION,
    )

    assert values(ENGINE.growth_rate(current, growth_prior, cutoff_at=FINANCIAL_CUTOFF)) == (
        Decimal("0.21"),
    )
    assert values(
        ENGINE.compound_annual_growth_rate(current, cagr_prior, years=2, cutoff_at=FINANCIAL_CUTOFF)
    ) == (Decimal("0.1"),)
    assert values(
        ENGINE.price_to_earnings_ratio(market_cap, earnings, cutoff_at=FINANCIAL_CUTOFF)
    ) == (Decimal("10"),)


def test_remaining_margin_and_valuation_formulas_are_explicit() -> None:
    revenue = fact(
        "Revenue",
        "200",
        period_start=date(2025, 1, 1),
        period_kind=FinancialPeriodKind.DURATION,
    )
    operating_income = fact(
        "OperatingIncome",
        "30",
        period_start=date(2025, 1, 1),
        period_kind=FinancialPeriodKind.DURATION,
    )
    net_income = fact(
        "NetIncome",
        "20",
        period_start=date(2025, 1, 1),
        period_kind=FinancialPeriodKind.DURATION,
    )
    market_cap = fact("MarketCapitalization", "500")
    enterprise_value = fact("EnterpriseValue", "600")
    ebitda = fact(
        "EBITDA",
        "50",
        period_start=date(2025, 1, 1),
        period_kind=FinancialPeriodKind.DURATION,
    )

    assert values(
        ENGINE.operating_margin(operating_income, revenue, cutoff_at=FINANCIAL_CUTOFF)
    ) == (Decimal("0.15"),)
    assert values(ENGINE.net_margin(net_income, revenue, cutoff_at=FINANCIAL_CUTOFF)) == (
        Decimal("0.1"),
    )
    assert values(ENGINE.price_to_sales_ratio(market_cap, revenue, cutoff_at=FINANCIAL_CUTOFF)) == (
        Decimal("2.5"),
    )
    assert values(
        ENGINE.enterprise_value_to_ebitda(enterprise_value, ebitda, cutoff_at=FINANCIAL_CUTOFF)
    ) == (Decimal("12"),)


def test_cagr_declared_years_must_match_fact_dates() -> None:
    prior = fact(
        "Revenue",
        "100",
        period_start=date(2023, 1, 1),
        period_end=date(2023, 12, 31),
        period_kind=FinancialPeriodKind.DURATION,
    )
    current = fact(
        "Revenue",
        "121",
        period_start=date(2025, 1, 1),
        period_kind=FinancialPeriodKind.DURATION,
    )

    with pytest.raises(ValueError, match="years must match"):
        ENGINE.compound_annual_growth_rate(current, prior, years=3, cutoff_at=FINANCIAL_CUTOFF)


def test_financial_currency_period_issuer_and_denominator_guards() -> None:
    assets = fact("CurrentAssets", "200")
    wrong_currency = fact("CurrentLiabilities", "100", currency=CurrencyCode.CANADIAN_DOLLAR)
    wrong_issuer = fact(
        "CurrentLiabilities",
        "100",
        issuer_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
    )
    zero = fact("CurrentLiabilities", "0")

    with pytest.raises(ValueError, match="currency"):
        ENGINE.current_ratio(assets, wrong_currency, cutoff_at=FINANCIAL_CUTOFF)
    with pytest.raises(ValueError, match="same issuer"):
        ENGINE.current_ratio(assets, wrong_issuer, cutoff_at=FINANCIAL_CUTOFF)
    with pytest.raises(ValueError, match="positive"):
        ENGINE.current_ratio(assets, zero, cutoff_at=FINANCIAL_CUTOFF)


def test_future_or_unretrieved_financial_inputs_fail_closed() -> None:
    future = fact(
        "CurrentAssets",
        "200",
        available_at=datetime(2026, 3, 2, tzinfo=UTC),
    )
    liabilities = fact("CurrentLiabilities", "100")

    with pytest.raises(ValueError, match="unavailable or unretrieved"):
        ENGINE.current_ratio(future, liabilities, cutoff_at=FINANCIAL_CUTOFF)


def test_financial_fact_and_metric_contracts_reject_invalid_temporal_data() -> None:
    with pytest.raises(ValidationError, match="period_start"):
        fact("Revenue", "10", period_kind=FinancialPeriodKind.DURATION)

    result = ENGINE.current_ratio(
        fact("CurrentAssets", "200"),
        fact("CurrentLiabilities", "100"),
        cutoff_at=FINANCIAL_CUTOFF,
    )
    with pytest.raises(ValidationError, match="unavailable"):
        MetricResult.model_validate(
            {
                **result.model_dump(),
                "knowledge_cutoff_at": datetime(2026, 1, 1, tzinfo=UTC),
            }
        )


def test_quantitative_contract_json_schemas_are_closed() -> None:
    for model in (FinancialFact, MetricResult):
        schema = model.model_json_schema()
        assert schema["additionalProperties"] is False


def test_metric_version_is_semantic_and_older_results_remain_readable() -> None:
    result = ENGINE.current_ratio(
        fact("CurrentAssets", "200"),
        fact("CurrentLiabilities", "100"),
        cutoff_at=FINANCIAL_CUTOFF,
    )

    assert (
        MetricResult.model_validate(
            {**result.model_dump(), "implementation_version": "0.9.0"}
        ).implementation_version
        == "0.9.0"
    )
    with pytest.raises(ValidationError, match="implementation_version"):
        MetricResult.model_validate({**result.model_dump(), "implementation_version": "v2"})
