"""Hash-anchored genuine SEC cases shared by local serving benchmarks."""

from __future__ import annotations

from typing import TypedDict

from kalki_market_intelligence.analysis.contracts import AnalystRole


class ServingBenchmarkCase(TypedDict):
    name: str
    accession: str
    cik: str
    company: str
    form: str
    url: str
    source_sha256: str
    role: AnalystRole
    required_fragments: tuple[str, ...]


SERVING_BENCHMARK_CASES: tuple[ServingBenchmarkCase, ...] = (
    {
        "name": "mccormick-current-report",
        "accession": "0000063754-26-000305",
        "cik": "63754",
        "company": "MCCORMICK & CO INC",
        "form": "8-K",
        "url": "https://www.sec.gov/Archives/edgar/data/63754/0000063754-26-000305.txt",
        "source_sha256": "290b019e66c27a9a9e9f7e061a5c3de2319711de7b3f617162de9a5489aeeb5f",
        "role": AnalystRole.CATALYST_ANALYST,
        "required_fragments": (
            "Ms. Bramman’s decision to resign",
            "effective September 1, 2026",
        ),
    },
    {
        "name": "target-quarterly-report",
        "accession": "0000027419-26-000042",
        "cik": "27419",
        "company": "TARGET CORP",
        "form": "10-Q",
        "url": "https://www.sec.gov/Archives/edgar/data/27419/0000027419-26-000042.txt",
        "source_sha256": "7033f9a606d3224069741cb2b056e688e1689cf040291741445de78584b598d8",
        "role": AnalystRole.BULL_BEAR_RISK_ANALYST,
        "required_fragments": (
            "Total assets $ 61,235",
            "impairment charges of $ 33 million",
            "effective at a reasonable assurance level",
        ),
    },
    {
        "name": "koss-annual-report",
        "accession": "0000056701-26-000034",
        "cik": "56701",
        "company": "KOSS CORP",
        "form": "10-K",
        "url": "https://www.sec.gov/Archives/edgar/data/56701/0000056701-26-000034.txt",
        "source_sha256": "34f4bdfc3e151abb5bc5a413819aef96ec26456874b806ab2d6ac811d4e26605",
        "role": AnalystRole.BULL_BEAR_RISK_ANALYST,
        "required_fragments": (
            "diversification by acquisition",
            "U.S.-China trade relations",
            "effective at the reasonable assurance level",
        ),
    },
)
