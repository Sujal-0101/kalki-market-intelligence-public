"""Pure Decimal algorithms. These functions have no I/O or model dependency."""

from __future__ import annotations

from collections.abc import Callable
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from functools import wraps

ZERO = Decimal(0)
ONE_HUNDRED = Decimal(100)
CALCULATION_CONTEXT = Context(prec=34, rounding=ROUND_HALF_EVEN)


def deterministic_decimal[**ParameterT, ReturnT](
    function: Callable[ParameterT, ReturnT],
) -> Callable[ParameterT, ReturnT]:
    """Make results independent of a caller's process-wide Decimal context."""

    @wraps(function)
    def wrapped(*args: ParameterT.args, **kwargs: ParameterT.kwargs) -> ReturnT:
        with localcontext(CALCULATION_CONTEXT):
            return function(*args, **kwargs)

    return wrapped


@deterministic_decimal
def mean(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("mean requires at least one value")
    return sum(values, ZERO) / Decimal(len(values))


@deterministic_decimal
def simple_returns(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    if len(values) < 2:
        raise ValueError("returns require at least two values")
    if any(value <= 0 for value in values):
        raise ValueError("return inputs must be positive")
    return tuple(
        current / previous - 1 for previous, current in zip(values, values[1:], strict=False)
    )


@deterministic_decimal
def rolling_sma(values: tuple[Decimal, ...], period: int) -> tuple[tuple[int, Decimal], ...]:
    _validate_period(values, period)
    return tuple(
        (index, mean(values[index - period + 1 : index + 1]))
        for index in range(period - 1, len(values))
    )


@deterministic_decimal
def ema(values: tuple[Decimal, ...], period: int) -> tuple[tuple[int, Decimal], ...]:
    """SMA-seeded EMA using alpha=2/(period+1)."""

    _validate_period(values, period)
    alpha = Decimal(2) / Decimal(period + 1)
    current = mean(values[:period])
    output = [(period - 1, current)]
    for index in range(period, len(values)):
        current = alpha * values[index] + (Decimal(1) - alpha) * current
        output.append((index, current))
    return tuple(output)


@deterministic_decimal
def rsi(values: tuple[Decimal, ...], period: int) -> tuple[tuple[int, Decimal], ...]:
    """Wilder RSI with an SMA seed followed by 1/period smoothing."""

    if period < 2:
        raise ValueError("RSI period must be at least two")
    if len(values) < period + 1:
        raise ValueError("RSI requires period+1 values")
    changes = tuple(
        current - previous for previous, current in zip(values, values[1:], strict=False)
    )
    gains = tuple(max(change, ZERO) for change in changes)
    losses = tuple(max(-change, ZERO) for change in changes)
    average_gain = mean(gains[:period])
    average_loss = mean(losses[:period])
    output = [(period, _rsi_value(average_gain, average_loss))]
    for change_index in range(period, len(changes)):
        average_gain = (average_gain * Decimal(period - 1) + gains[change_index]) / Decimal(period)
        average_loss = (average_loss * Decimal(period - 1) + losses[change_index]) / Decimal(period)
        output.append((change_index + 1, _rsi_value(average_gain, average_loss)))
    return tuple(output)


@deterministic_decimal
def macd(
    values: tuple[Decimal, ...], fast_period: int, slow_period: int, signal_period: int
) -> tuple[tuple[int, Decimal, Decimal, Decimal], ...]:
    if fast_period < 1 or slow_period <= fast_period or signal_period < 1:
        raise ValueError("MACD requires 1 <= fast < slow and a positive signal period")
    if len(values) < slow_period + signal_period - 1:
        raise ValueError("MACD has insufficient values for its slow and signal periods")
    fast = dict(ema(values, fast_period))
    slow = ema(values, slow_period)
    line = tuple((index, fast[index] - slow_value) for index, slow_value in slow)
    signal_values = ema(tuple(value for _, value in line), signal_period)
    output: list[tuple[int, Decimal, Decimal, Decimal]] = []
    for line_index, signal in signal_values:
        source_index, macd_line = line[line_index]
        output.append((source_index, macd_line, signal, macd_line - signal))
    return tuple(output)


@deterministic_decimal
def true_ranges(
    highs: tuple[Decimal, ...], lows: tuple[Decimal, ...], closes: tuple[Decimal, ...]
) -> tuple[Decimal, ...]:
    if not highs or len(highs) != len(lows) or len(highs) != len(closes):
        raise ValueError("true range inputs must be non-empty and equal length")
    ranges = [highs[0] - lows[0]]
    for index in range(1, len(highs)):
        ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    return tuple(ranges)


@deterministic_decimal
def atr(
    highs: tuple[Decimal, ...],
    lows: tuple[Decimal, ...],
    closes: tuple[Decimal, ...],
    period: int,
) -> tuple[tuple[int, Decimal], ...]:
    """Wilder ATR; the seed uses period true ranges after the first close."""

    ranges = true_ranges(highs, lows, closes)
    if period < 1 or len(ranges) < period + 1:
        raise ValueError("ATR requires period+1 bars")
    current = mean(ranges[1 : period + 1])
    output = [(period, current)]
    for index in range(period + 1, len(ranges)):
        current = (current * Decimal(period - 1) + ranges[index]) / Decimal(period)
        output.append((index, current))
    return tuple(output)


@deterministic_decimal
def sample_standard_deviation(values: tuple[Decimal, ...]) -> Decimal:
    if len(values) < 2:
        raise ValueError("sample standard deviation requires at least two values")
    average = mean(values)
    variance = sum(((value - average) ** 2 for value in values), ZERO) / Decimal(len(values) - 1)
    return variance.sqrt()


@deterministic_decimal
def annualized_volatility(values: tuple[Decimal, ...], periods_per_year: int) -> Decimal:
    if periods_per_year < 1:
        raise ValueError("periods_per_year must be positive")
    returns = simple_returns(values)
    return sample_standard_deviation(returns) * Decimal(periods_per_year).sqrt()


@deterministic_decimal
def beta(asset_returns: tuple[Decimal, ...], benchmark_returns: tuple[Decimal, ...]) -> Decimal:
    if len(asset_returns) != len(benchmark_returns) or len(asset_returns) < 2:
        raise ValueError("beta requires equal return series with at least two observations")
    asset_mean = mean(asset_returns)
    benchmark_mean = mean(benchmark_returns)
    covariance_sum = sum(
        (
            (asset - asset_mean) * (benchmark - benchmark_mean)
            for asset, benchmark in zip(asset_returns, benchmark_returns, strict=True)
        ),
        ZERO,
    )
    benchmark_variance_sum = sum(
        ((value - benchmark_mean) ** 2 for value in benchmark_returns), ZERO
    )
    if benchmark_variance_sum == 0:
        raise ValueError("beta is undefined when benchmark returns have zero variance")
    return covariance_sum / benchmark_variance_sum


def _rsi_value(average_gain: Decimal, average_loss: Decimal) -> Decimal:
    if average_loss == 0:
        return ONE_HUNDRED if average_gain > 0 else Decimal(50)
    relative_strength = average_gain / average_loss
    return ONE_HUNDRED - ONE_HUNDRED / (Decimal(1) + relative_strength)


def _validate_period(values: tuple[Decimal, ...], period: int) -> None:
    if period < 1:
        raise ValueError("period must be positive")
    if len(values) < period:
        raise ValueError("insufficient values for period")
