"""Lineage-preserving wrappers around deterministic Decimal algorithms."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from kalki_market_intelligence.contracts.domain import CurrencyCode
from kalki_market_intelligence.providers.market_data.contracts import (
    BarSeries,
    DailyBar,
    FreshnessStatus,
    PriceAdjustment,
    VolumeAdjustment,
)
from kalki_market_intelligence.quantitative import algorithms
from kalki_market_intelligence.quantitative.contracts import (
    CalculationInput,
    FinancialFact,
    FinancialPeriodKind,
    FinancialUnit,
    InputValue,
    MetricParameter,
    MetricPoint,
    MetricResult,
)


class QuantitativeEngine:
    """Pure deterministic calculations with strict point-in-time input gates."""

    @algorithms.deterministic_decimal
    def cumulative_return(self, series: BarSeries) -> MetricResult:
        bars = _validated_bars(series, minimum=2, adjusted_prices=True)
        value = bars[-1].close / bars[0].close - 1
        return _bar_result(
            "cumulative_price_return",
            series,
            bars,
            ((bars[-1].session_date, "value", value),),
            "decimal_fraction",
            ("close",),
        )

    @algorithms.deterministic_decimal
    def simple_moving_average(self, series: BarSeries, *, period: int) -> MetricResult:
        bars = _validated_bars(series, minimum=period, adjusted_prices=True)
        values = tuple(bar.close for bar in bars)
        points = tuple(
            (bars[index].session_date, "value", value)
            for index, value in algorithms.rolling_sma(values, period)
        )
        return _bar_result(
            "simple_moving_average",
            series,
            bars,
            points,
            "currency",
            ("close",),
            parameters=(MetricParameter(name="period", value=str(period)),),
        )

    @algorithms.deterministic_decimal
    def exponential_moving_average(self, series: BarSeries, *, period: int) -> MetricResult:
        bars = _validated_bars(series, minimum=period, adjusted_prices=True)
        values = tuple(bar.close for bar in bars)
        points = tuple(
            (bars[index].session_date, "value", value)
            for index, value in algorithms.ema(values, period)
        )
        return _bar_result(
            "exponential_moving_average",
            series,
            bars,
            points,
            "currency",
            ("close",),
            parameters=(
                MetricParameter(name="period", value=str(period)),
                MetricParameter(name="seed", value="simple_moving_average"),
            ),
        )

    @algorithms.deterministic_decimal
    def relative_strength_index(self, series: BarSeries, *, period: int = 14) -> MetricResult:
        bars = _validated_bars(series, minimum=period + 1, adjusted_prices=True)
        values = tuple(bar.close for bar in bars)
        points = tuple(
            (bars[index].session_date, "value", value)
            for index, value in algorithms.rsi(values, period)
        )
        return _bar_result(
            "relative_strength_index",
            series,
            bars,
            points,
            "index_0_100",
            ("close",),
            currency=None,
            parameters=(
                MetricParameter(name="period", value=str(period)),
                MetricParameter(name="smoothing", value="wilder"),
            ),
        )

    @algorithms.deterministic_decimal
    def macd(
        self,
        series: BarSeries,
        *,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> MetricResult:
        bars = _validated_bars(
            series, minimum=slow_period + signal_period - 1, adjusted_prices=True
        )
        values = tuple(bar.close for bar in bars)
        outputs = algorithms.macd(values, fast_period, slow_period, signal_period)
        points = tuple(
            point
            for index, line, signal, histogram in outputs
            for point in (
                (bars[index].session_date, "line", line),
                (bars[index].session_date, "signal", signal),
                (bars[index].session_date, "histogram", histogram),
            )
        )
        return _bar_result(
            "moving_average_convergence_divergence",
            series,
            bars,
            points,
            "currency",
            ("close",),
            parameters=(
                MetricParameter(name="fast_period", value=str(fast_period)),
                MetricParameter(name="slow_period", value=str(slow_period)),
                MetricParameter(name="signal_period", value=str(signal_period)),
                MetricParameter(name="seed", value="simple_moving_average"),
            ),
        )

    @algorithms.deterministic_decimal
    def average_true_range(self, series: BarSeries, *, period: int = 14) -> MetricResult:
        bars = _validated_bars(series, minimum=period + 1, adjusted_prices=True)
        outputs = algorithms.atr(
            tuple(bar.high for bar in bars),
            tuple(bar.low for bar in bars),
            tuple(bar.close for bar in bars),
            period,
        )
        points = tuple((bars[index].session_date, "value", value) for index, value in outputs)
        return _bar_result(
            "average_true_range",
            series,
            bars,
            points,
            "currency",
            ("high", "low", "close"),
            parameters=(
                MetricParameter(name="period", value=str(period)),
                MetricParameter(name="smoothing", value="wilder"),
            ),
        )

    @algorithms.deterministic_decimal
    def annualized_volatility(
        self, series: BarSeries, *, periods_per_year: int = 252
    ) -> MetricResult:
        bars = _validated_bars(series, minimum=3, adjusted_prices=True)
        value = algorithms.annualized_volatility(tuple(bar.close for bar in bars), periods_per_year)
        return _bar_result(
            "annualized_historical_volatility",
            series,
            bars,
            ((bars[-1].session_date, "value", value),),
            "decimal_fraction",
            ("close",),
            currency=None,
            parameters=(
                MetricParameter(name="return_type", value="simple"),
                MetricParameter(name="sample_denominator", value="n-1"),
                MetricParameter(name="periods_per_year", value=str(periods_per_year)),
            ),
        )

    @algorithms.deterministic_decimal
    def relative_volume(self, series: BarSeries, *, comparison_period: int = 20) -> MetricResult:
        bars = _validated_bars(
            series,
            minimum=comparison_period + 1,
            adjusted_prices=False,
            adjusted_volume=True,
        )
        comparison = bars[-comparison_period - 1 : -1]
        average = algorithms.mean(tuple(Decimal(bar.volume) for bar in comparison))
        if average == 0:
            raise ValueError("relative volume is undefined when comparison volume is zero")
        value = Decimal(bars[-1].volume) / average
        consumed = (*comparison, bars[-1])
        return _bar_result(
            "relative_volume",
            series,
            consumed,
            ((bars[-1].session_date, "value", value),),
            "decimal_ratio",
            ("volume",),
            currency=None,
            parameters=(
                MetricParameter(name="comparison_period", value=str(comparison_period)),
                MetricParameter(name="latest_excluded_from_average", value="true"),
            ),
        )

    @algorithms.deterministic_decimal
    def fifty_two_week_position(
        self, series: BarSeries, *, lookback_sessions: int = 252
    ) -> MetricResult:
        bars = _validated_bars(series, minimum=lookback_sessions, adjusted_prices=True)
        consumed = bars[-lookback_sessions:]
        closes = tuple(bar.close for bar in consumed)
        low = min(closes)
        high = max(closes)
        if high == low:
            raise ValueError("52-week position is undefined for a flat range")
        value = (closes[-1] - low) / (high - low)
        return _bar_result(
            "fifty_two_week_position",
            series,
            consumed,
            ((consumed[-1].session_date, "value", value),),
            "decimal_fraction_0_1",
            ("close",),
            currency=None,
            parameters=(MetricParameter(name="lookback_sessions", value=str(lookback_sessions)),),
        )

    @algorithms.deterministic_decimal
    def maximum_drawdown(self, series: BarSeries) -> MetricResult:
        bars = _validated_bars(series, minimum=2, adjusted_prices=True)
        peak = bars[0].close
        worst = Decimal(0)
        for bar in bars:
            peak = max(peak, bar.close)
            worst = min(worst, bar.close / peak - 1)
        return _bar_result(
            "maximum_drawdown",
            series,
            bars,
            ((bars[-1].session_date, "value", worst),),
            "decimal_fraction",
            ("close",),
            currency=None,
        )

    @algorithms.deterministic_decimal
    def benchmark_relative_return(self, asset: BarSeries, benchmark: BarSeries) -> MetricResult:
        asset_bars, benchmark_bars = _matched_bars(asset, benchmark, minimum=2)
        value = (asset_bars[-1].close / asset_bars[0].close - 1) - (
            benchmark_bars[-1].close / benchmark_bars[0].close - 1
        )
        return _paired_bar_result(
            "benchmark_relative_return",
            asset,
            asset_bars,
            benchmark_bars,
            value,
            "decimal_fraction",
        )

    @algorithms.deterministic_decimal
    def beta(self, asset: BarSeries, benchmark: BarSeries) -> MetricResult:
        asset_bars, benchmark_bars = _matched_bars(asset, benchmark, minimum=3)
        value = algorithms.beta(
            algorithms.simple_returns(tuple(bar.close for bar in asset_bars)),
            algorithms.simple_returns(tuple(bar.close for bar in benchmark_bars)),
        )
        return _paired_bar_result("beta", asset, asset_bars, benchmark_bars, value, "decimal_ratio")

    @algorithms.deterministic_decimal
    def current_ratio(
        self,
        current_assets: FinancialFact,
        current_liabilities: FinancialFact,
        *,
        cutoff_at: datetime,
    ) -> MetricResult:
        return self._same_period_ratio(
            "current_ratio",
            current_assets,
            current_liabilities,
            cutoff_at=cutoff_at,
            positive_denominator=True,
        )

    @algorithms.deterministic_decimal
    def debt_to_equity_ratio(
        self, total_debt: FinancialFact, shareholders_equity: FinancialFact, *, cutoff_at: datetime
    ) -> MetricResult:
        return self._same_period_ratio(
            "debt_to_equity_ratio",
            total_debt,
            shareholders_equity,
            cutoff_at=cutoff_at,
            positive_denominator=True,
        )

    @algorithms.deterministic_decimal
    def gross_margin(
        self, gross_profit: FinancialFact, revenue: FinancialFact, *, cutoff_at: datetime
    ) -> MetricResult:
        return self._same_period_ratio(
            "gross_margin",
            gross_profit,
            revenue,
            cutoff_at=cutoff_at,
            duration=True,
            positive_denominator=True,
        )

    @algorithms.deterministic_decimal
    def operating_margin(
        self, operating_income: FinancialFact, revenue: FinancialFact, *, cutoff_at: datetime
    ) -> MetricResult:
        return self._same_period_ratio(
            "operating_margin",
            operating_income,
            revenue,
            cutoff_at=cutoff_at,
            duration=True,
            positive_denominator=True,
        )

    @algorithms.deterministic_decimal
    def net_margin(
        self, net_income: FinancialFact, revenue: FinancialFact, *, cutoff_at: datetime
    ) -> MetricResult:
        return self._same_period_ratio(
            "net_margin",
            net_income,
            revenue,
            cutoff_at=cutoff_at,
            duration=True,
            positive_denominator=True,
        )

    @algorithms.deterministic_decimal
    def return_on_equity(
        self,
        net_income: FinancialFact,
        beginning_equity: FinancialFact,
        ending_equity: FinancialFact,
        *,
        cutoff_at: datetime,
    ) -> MetricResult:
        cutoff = _as_utc_datetime(cutoff_at)
        _validate_financial_facts((net_income, beginning_equity, ending_equity), cutoff)
        if net_income.period_kind is not FinancialPeriodKind.DURATION:
            raise ValueError("return on equity requires duration net income")
        if (
            beginning_equity.period_kind is not FinancialPeriodKind.INSTANT
            or ending_equity.period_kind is not FinancialPeriodKind.INSTANT
        ):
            raise ValueError("return on equity requires instant equity facts")
        if (
            net_income.period_start != beginning_equity.period_end
            or net_income.period_end != ending_equity.period_end
        ):
            raise ValueError("equity dates must match the income period boundaries")
        _require_monetary_same_currency((net_income, beginning_equity, ending_equity))
        average_equity = (beginning_equity.value + ending_equity.value) / Decimal(2)
        if average_equity <= 0:
            raise ValueError("return on equity requires positive average equity")
        return _financial_result(
            "return_on_equity",
            net_income.value / average_equity,
            (net_income, beginning_equity, ending_equity),
            cutoff,
            "decimal_ratio",
        )

    @algorithms.deterministic_decimal
    def growth_rate(
        self, current: FinancialFact, prior: FinancialFact, *, cutoff_at: datetime
    ) -> MetricResult:
        cutoff = _as_utc_datetime(cutoff_at)
        _validate_comparable_facts(current, prior, cutoff)
        if current.period_end <= prior.period_end:
            raise ValueError("current fact must follow prior fact")
        if current.period_kind is FinancialPeriodKind.DURATION:
            assert current.period_start is not None and prior.period_start is not None
            current_days = (current.period_end - current.period_start).days
            prior_days = (prior.period_end - prior.period_start).days
            if abs(current_days - prior_days) > 7:
                raise ValueError("growth periods must have comparable durations")
        if prior.value <= 0:
            raise ValueError("growth rate requires a positive prior value")
        return _financial_result(
            "period_over_period_growth",
            current.value / prior.value - 1,
            (current, prior),
            cutoff,
            "decimal_fraction",
        )

    @algorithms.deterministic_decimal
    def compound_annual_growth_rate(
        self,
        current: FinancialFact,
        prior: FinancialFact,
        *,
        years: int,
        cutoff_at: datetime,
    ) -> MetricResult:
        cutoff = _as_utc_datetime(cutoff_at)
        _validate_comparable_facts(current, prior, cutoff)
        if years < 1 or current.value <= 0 or prior.value <= 0:
            raise ValueError("CAGR requires positive values and years")
        try:
            expected_prior_end = current.period_end.replace(year=current.period_end.year - years)
        except ValueError as error:
            raise ValueError("CAGR dates must define whole calendar years") from error
        if prior.period_end != expected_prior_end:
            raise ValueError("CAGR years must match the financial fact end dates")
        value = (current.value / prior.value) ** (Decimal(1) / Decimal(years)) - 1
        return _financial_result(
            "compound_annual_growth_rate",
            value,
            (current, prior),
            cutoff,
            "decimal_fraction",
            parameters=(MetricParameter(name="years", value=str(years)),),
        )

    @algorithms.deterministic_decimal
    def price_to_earnings_ratio(
        self,
        market_capitalization: FinancialFact,
        net_income: FinancialFact,
        *,
        cutoff_at: datetime,
    ) -> MetricResult:
        return self._valuation_ratio(
            "price_to_earnings_ratio", market_capitalization, net_income, cutoff_at
        )

    @algorithms.deterministic_decimal
    def price_to_sales_ratio(
        self, market_capitalization: FinancialFact, revenue: FinancialFact, *, cutoff_at: datetime
    ) -> MetricResult:
        return self._valuation_ratio(
            "price_to_sales_ratio", market_capitalization, revenue, cutoff_at
        )

    @algorithms.deterministic_decimal
    def enterprise_value_to_ebitda(
        self, enterprise_value: FinancialFact, ebitda: FinancialFact, *, cutoff_at: datetime
    ) -> MetricResult:
        return self._valuation_ratio(
            "enterprise_value_to_ebitda", enterprise_value, ebitda, cutoff_at
        )

    def _same_period_ratio(
        self,
        metric_name: str,
        numerator: FinancialFact,
        denominator: FinancialFact,
        *,
        cutoff_at: datetime,
        duration: bool = False,
        positive_denominator: bool = False,
    ) -> MetricResult:
        cutoff = _as_utc_datetime(cutoff_at)
        _validate_financial_facts((numerator, denominator), cutoff)
        expected_kind = FinancialPeriodKind.DURATION if duration else FinancialPeriodKind.INSTANT
        if (
            numerator.period_kind is not expected_kind
            or denominator.period_kind is not expected_kind
        ):
            raise ValueError(f"{metric_name} inputs have incompatible period kinds")
        if (
            numerator.period_start != denominator.period_start
            or numerator.period_end != denominator.period_end
        ):
            raise ValueError(f"{metric_name} inputs must cover the same period")
        _require_monetary_same_currency((numerator, denominator))
        _validate_denominator(denominator.value, positive=positive_denominator)
        return _financial_result(
            metric_name,
            numerator.value / denominator.value,
            (numerator, denominator),
            cutoff,
            "decimal_ratio",
        )

    def _valuation_ratio(
        self,
        metric_name: str,
        numerator: FinancialFact,
        denominator: FinancialFact,
        cutoff_at: datetime,
    ) -> MetricResult:
        cutoff = _as_utc_datetime(cutoff_at)
        _validate_financial_facts((numerator, denominator), cutoff)
        if numerator.period_kind is not FinancialPeriodKind.INSTANT:
            raise ValueError("valuation numerator must be an instant fact")
        if denominator.period_kind is not FinancialPeriodKind.DURATION:
            raise ValueError("valuation denominator must be a duration fact")
        if denominator.period_end > numerator.period_end:
            raise ValueError("valuation denominator cannot end after the valuation date")
        _require_monetary_same_currency((numerator, denominator))
        _validate_denominator(denominator.value, positive=True)
        return _financial_result(
            metric_name,
            numerator.value / denominator.value,
            (numerator, denominator),
            cutoff,
            "decimal_ratio",
        )


def _validated_bars(
    series: BarSeries,
    *,
    minimum: int,
    adjusted_prices: bool,
    adjusted_volume: bool = False,
) -> tuple[DailyBar, ...]:
    if minimum < 1:
        raise ValueError("minimum bar count must be positive")
    if series.quality.freshness_status is not FreshnessStatus.CURRENT:
        raise ValueError("quantitative calculations require explicitly current input data")
    if len(series.bars) < minimum:
        raise ValueError(f"calculation requires at least {minimum} bars")
    if adjusted_prices and series.request.adjustment is PriceAdjustment.UNADJUSTED:
        raise ValueError("price calculation requires a split-adjusted price basis")
    if adjusted_volume and series.request.volume_adjustment is VolumeAdjustment.UNADJUSTED:
        raise ValueError("volume calculation requires a split-adjusted volume basis")
    return series.bars


def _matched_bars(
    asset: BarSeries, benchmark: BarSeries, *, minimum: int
) -> tuple[tuple[DailyBar, ...], tuple[DailyBar, ...]]:
    asset_all = _validated_bars(asset, minimum=minimum, adjusted_prices=True)
    benchmark_all = _validated_bars(benchmark, minimum=minimum, adjusted_prices=True)
    if asset.request.currency is not benchmark.request.currency:
        raise ValueError("asset and benchmark currencies must match")
    if asset.request.adjustment is not benchmark.request.adjustment:
        raise ValueError("asset and benchmark adjustment bases must match")
    if asset.request.knowledge_cutoff_at != benchmark.request.knowledge_cutoff_at:
        raise ValueError("asset and benchmark knowledge cutoffs must match")
    asset_by_date = {bar.session_date: bar for bar in asset_all}
    benchmark_by_date = {bar.session_date: bar for bar in benchmark_all}
    dates = sorted(asset_by_date.keys() & benchmark_by_date.keys())
    if len(dates) < minimum:
        raise ValueError(f"asset and benchmark require at least {minimum} matched sessions")
    return (
        tuple(asset_by_date[session] for session in dates),
        tuple(benchmark_by_date[session] for session in dates),
    )


def _bar_result(
    metric_name: str,
    series: BarSeries,
    bars: tuple[DailyBar, ...],
    points: tuple[tuple[date, str, Decimal], ...],
    unit: str,
    value_names: tuple[str, ...],
    *,
    currency: CurrencyCode | None | object = ...,
    parameters: tuple[MetricParameter, ...] = (),
) -> MetricResult:
    result_currency = series.request.currency if currency is ... else currency
    assert result_currency is None or isinstance(result_currency, CurrencyCode)
    return MetricResult(
        metric_name=metric_name,
        as_of_date=bars[-1].session_date,
        knowledge_cutoff_at=series.request.knowledge_cutoff_at,
        unit=unit,
        currency=result_currency,
        parameters=parameters,
        points=tuple(
            MetricPoint(effective_date=effective_date, component=component, value=value)
            for effective_date, component, value in points
        ),
        inputs=tuple(_bar_input(bar, value_names) for bar in bars),
    )


def _paired_bar_result(
    metric_name: str,
    asset: BarSeries,
    asset_bars: tuple[DailyBar, ...],
    benchmark_bars: tuple[DailyBar, ...],
    value: Decimal,
    unit: str,
) -> MetricResult:
    inputs = tuple(
        _bar_input(bar, ("close",), input_kind=kind)
        for kind, bars in (("asset_bar", asset_bars), ("benchmark_bar", benchmark_bars))
        for bar in bars
    )
    return MetricResult(
        metric_name=metric_name,
        as_of_date=asset_bars[-1].session_date,
        knowledge_cutoff_at=asset.request.knowledge_cutoff_at,
        unit=unit,
        currency=None,
        points=(
            MetricPoint(effective_date=asset_bars[-1].session_date, component="value", value=value),
        ),
        inputs=inputs,
    )


def _bar_input(
    bar: DailyBar, value_names: tuple[str, ...], *, input_kind: str = "market_bar"
) -> CalculationInput:
    values_by_name = {
        "open": (bar.open, "currency"),
        "high": (bar.high, "currency"),
        "low": (bar.low, "currency"),
        "close": (bar.close, "currency"),
        "volume": (Decimal(bar.volume), "shares"),
    }
    return CalculationInput(
        input_id=f"{input_kind}:{bar.instrument_id}:{bar.session_date}:{bar.source_content_sha256}",
        input_kind=input_kind,
        subject_id=bar.instrument_id,
        effective_date=bar.session_date,
        values=tuple(
            InputValue(name=name, value=values_by_name[name][0], unit=values_by_name[name][1])
            for name in value_names
        ),
        currency=bar.currency,
        price_adjustment=bar.adjustment,
        volume_adjustment=bar.volume_adjustment,
        available_at=bar.available_at,
        retrieved_at=bar.retrieved_at,
        source_record_id=bar.source_record_id,
        source_content_sha256=bar.source_content_sha256,
    )


def _financial_result(
    metric_name: str,
    value: Decimal,
    facts: tuple[FinancialFact, ...],
    cutoff_at: datetime,
    unit: str,
    *,
    parameters: tuple[MetricParameter, ...] = (),
) -> MetricResult:
    cutoff = _as_utc_datetime(cutoff_at)
    as_of = max(fact.period_end for fact in facts)
    return MetricResult(
        metric_name=metric_name,
        as_of_date=as_of,
        knowledge_cutoff_at=cutoff,
        unit=unit,
        currency=None,
        parameters=parameters,
        points=(MetricPoint(effective_date=as_of, component="value", value=value),),
        inputs=tuple(_financial_input(fact) for fact in facts),
    )


def _financial_input(fact: FinancialFact) -> CalculationInput:
    return CalculationInput(
        input_id=f"financial_fact:{fact.fact_id}",
        input_kind="financial_fact",
        subject_id=fact.issuer_id,
        period_start=fact.period_start,
        effective_date=fact.period_end,
        values=(InputValue(name=fact.concept, value=fact.value, unit=fact.unit.value),),
        currency=fact.currency,
        available_at=fact.available_at,
        retrieved_at=fact.retrieved_at,
        source_record_id=fact.source_record_id,
        source_content_sha256=fact.source_content_sha256,
    )


def _validate_financial_facts(facts: tuple[FinancialFact, ...], cutoff: datetime) -> None:
    cutoff_at = _as_utc_datetime(cutoff)
    if not facts:
        raise ValueError("financial calculation requires inputs")
    issuer = facts[0].issuer_id
    for fact in facts:
        if fact.issuer_id != issuer:
            raise ValueError("financial inputs must belong to the same issuer")
        if fact.available_at > cutoff_at or fact.retrieved_at > cutoff_at:
            raise ValueError("financial input was unavailable or unretrieved at the cutoff")
        if fact.period_end > cutoff_at.date():
            raise ValueError("financial input period ends after the cutoff")


def _validate_comparable_facts(
    current: FinancialFact, prior: FinancialFact, cutoff: datetime
) -> None:
    _validate_financial_facts((current, prior), cutoff)
    if current.concept != prior.concept:
        raise ValueError("growth inputs must use the same concept")
    if current.unit is not prior.unit or current.currency is not prior.currency:
        raise ValueError("growth inputs must use the same unit and currency")
    if current.period_kind is not prior.period_kind:
        raise ValueError("growth inputs must use the same period kind")


def _require_monetary_same_currency(facts: tuple[FinancialFact, ...]) -> None:
    if any(fact.unit is not FinancialUnit.CURRENCY for fact in facts):
        raise ValueError("ratio inputs must use currency units")
    if len({fact.currency for fact in facts}) != 1:
        raise ValueError("ratio inputs must use the same currency")


def _validate_denominator(value: Decimal, *, positive: bool) -> None:
    if value == 0 or (positive and value < 0):
        qualifier = "positive" if positive else "non-zero"
        raise ValueError(f"ratio denominator must be {qualifier}")


def _as_utc_datetime(value: datetime) -> datetime:
    from kalki_market_intelligence.contracts.common import normalize_utc

    return normalize_utc(value)
