# Third-party licenses and source material

Kalki's owner-authored source and documentation are licensed under the
[Apache License 2.0](../LICENSE). That project license does **not** relicense
dependencies, container bases, local models, provider data, or third-party source
material. Each remains governed by its upstream license or terms.

> [!CAUTION]
> This is a technical inventory, not legal advice. Versions and upstream terms can
> change. Recheck the exact artifacts you distribute, especially wheels, container
> images, model weights, and installer binaries.

## Publication conclusion

The repository does not vendor dependency source trees or model weights. Its direct
Python dependencies are resolved from exact hashed lock files; PostgreSQL, Docker,
Ollama and Qwen are installed or downloaded separately. The only bundled visual
assets are owner-authored. No incompatibility was identified that prevents the owner
from licensing original Kalki source under Apache-2.0.

That conclusion is deliberately limited to publishing this source tree. Anyone who
redistributes built wheels, container images, Python runtimes, model weights, or
other binaries must inventory the exact transitive contents, retain required
notices/source offers, and comply with each component's terms. In particular, the
LGPL-licensed Psycopg packages require release-specific review when binaries are
distributed.

## Direct Python runtime dependencies

Versions below are the exact direct pins in `pyproject.toml` and the lock files for
this release candidate. The license labels come from installed package metadata and
upstream project metadata.

| Component | Pinned version | Upstream license | How Kalki uses it |
|---|---:|---|---|
| [argon2-cffi](https://github.com/hynek/argon2-cffi) | 25.1.0 | MIT | Admin password hashing/verification |
| [FastAPI](https://github.com/fastapi/fastapi) | 0.141.1 | MIT | Private and public HTTP applications |
| [Jinja2](https://github.com/pallets/jinja) | 3.1.6 | BSD-3-Clause | Server-rendered HTML templates |
| [Pydantic](https://github.com/pydantic/pydantic) | 2.13.4 | MIT | Closed data contracts and validation |
| [pydantic-settings](https://github.com/pydantic/pydantic-settings) | 2.15.0 | MIT | Environment-driven configuration |
| [python-multipart](https://github.com/Kludex/python-multipart) | 0.0.32 | Apache-2.0 | Bounded admin form parsing |
| [Psycopg](https://www.psycopg.org/psycopg3/docs/) | 3.3.4 | LGPL-3.0-only | PostgreSQL driver, binary extra and pooling |
| [Uvicorn](https://github.com/Kludex/uvicorn) | 0.52.4 | BSD-3-Clause | ASGI server |
| [discord.py](https://github.com/Rapptz/discord.py) | 2.6.4 | MIT | Optional private Discord Gateway intake |
| [exchange-calendars](https://github.com/gerrymanoim/exchange_calendars) | 4.13.2 | Apache-2.0 | Deterministic exchange-session calendars |

Development-only direct dependencies (`pytest`, `Ruff`, `mypy`, and `httpx2`) and
all transitive packages remain under their own terms. `requirements.lock` and
`requirements-dev.lock` identify exact resolved artifacts and hashes; they are not
license substitutes. NumPy, pandas, and some other wheels include bundled
third-party components and notices, which is another reason to generate an SBOM and
license report from the exact built image before distributing binaries.

## Runtime, container and model components

| Component | Terms established from | Distribution boundary |
|---|---|---|
| [PostgreSQL](https://www.postgresql.org/about/licence/) | PostgreSQL License | Pinned container image; database software is not relicensed by Kalki |
| [Moby / Docker Engine](https://github.com/moby/moby/blob/master/LICENSE) | Apache-2.0 | Installed host runtime; Docker Desktop is not required by the Linux guide |
| [Docker Compose](https://github.com/docker/compose/blob/main/LICENSE) | Apache-2.0 | Host CLI/plugin; not bundled source |
| [Python](https://docs.python.org/3/license.html) | PSF license stack | Base container/runtime; retain applicable runtime notices in redistributed images |
| [Ollama source repository](https://github.com/ollama/ollama/blob/main/LICENSE) | MIT | Local model server downloaded separately; verify the exact Linux artifact used |
| [Qwen3 open-weight models](https://github.com/QwenLM/Qwen3#license-agreement) | Apache-2.0 stated by Qwen for open weights | `qwen3:4b` is downloaded separately; no weight file is in Git or the export |
| [cloudflared](https://github.com/cloudflare/cloudflared/blob/master/LICENSE) | Apache-2.0 plus Cloudflare service terms | Optional connector profile; use of Cloudflare is a separate account/terms decision |
| Gemma model family | Separate Google model terms | Disabled, not loaded, not bundled, and not covered by Kalki's Apache license |
| Twelve Data | Provider terms | Optional provider remains disabled; no account, key, or provider data is bundled |

The accepted Qwen runtime lineage remains the frozen `qwen3:4b` digest documented
in [Observation Baseline V2](PHASE45_OBSERVATION_BASELINE_V2.md). A model name,
license family, or larger parameter count does not establish compatibility with that
baseline; model changes require their own technical and licensing review.

## Repository-bundled material

| Material | Current classification | Public-release handling |
|---|---|---|
| SVG, CSS and social-card PNG | Owner-authored; see [asset inventory](ASSET_LICENSES.md) | Included under the project license |
| Market/backtest fixtures under `data/fixtures/` | Explicitly synthetic | Included for deterministic tests; not real market evidence |
| Novelty fixtures | Fully synthetic, reserved identities/URLs | Replaced the former NVIDIA IR/SEC prose pair while preserving the recap regression |
| Financing/accounting/ownership SEC excerpts | Bounded public EDGAR filing material | Retained with SEC provenance; not owner-authored or relicensed |
| Model weights, local data, backups, logs, human research | Not repository-bundled | Explicitly excluded from Git and public export |

The SEC says public EDGAR filing content is free to access and reuse in its
[Webmaster Frequently Asked Questions](https://www.sec.gov/about/webmaster-frequently-asked-questions).
Kalki still preserves source identity and does not imply that SEC endorses this
project. Company names and marks belong to their respective owners.

## Before distributing something beyond source

For a wheel, image, appliance, hosted service, or model bundle:

1. build from an immutable public release;
2. generate an SBOM and a transitive license inventory from the exact artifact;
3. retain all required copyright, license, attribution, and source-offer material;
4. verify the exact Ollama binary and model manifest/weight license;
5. review LGPL obligations for the Psycopg artifacts actually shipped;
6. review optional provider/service terms separately; and
7. never include `.env`, secrets, databases, backups, logs, model caches, or private
   human research.
