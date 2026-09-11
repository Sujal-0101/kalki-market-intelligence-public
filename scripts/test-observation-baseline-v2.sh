#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
venv_bin="$repository_dir/.venv/bin"

"$venv_bin/pytest" -q
"$venv_bin/ruff" format --check "$repository_dir"
"$venv_bin/ruff" check "$repository_dir"
"$venv_bin/mypy" --strict "$repository_dir/src" "$repository_dir/tests"
"$venv_bin/python" -m pip check

docker compose -f "$repository_dir/compose.production.yaml" config --quiet
docker compose -f "$repository_dir/compose.production.yaml" \
    --profile supporting-outcomes config --quiet
docker compose -f "$repository_dir/compose.production.yaml" \
    -f "$repository_dir/compose.cloudflare.yaml" config --quiet

for script in "$repository_dir"/scripts/*.sh
do
    sh -n "$script"
done

for gate in \
    test-analyst-attempt-postgres.sh \
    test-hierarchical-verifier-postgres.sh \
    test-funnel-telemetry-postgres.sh \
    test-autonomous-screening-postgres.sh \
    test-validated-sec-links-postgres.sh \
    test-event-novelty-postgres.sh \
    test-focus-universe-postgres.sh \
    test-engineering-measurements-postgres.sh \
    test-ownership-postgres.sh \
    test-financing-postgres.sh \
    test-accounting-postgres.sh \
    test-analyst-attempt-recovery-postgres.sh \
    test-filing-change-lifecycle-postgres.sh \
    test-contradiction-postgres.sh \
    test-prospective-outcomes-postgres.sh
do
    "$repository_dir/scripts/$gate"
done

echo "Observation Baseline V2 engineering gate passed."
