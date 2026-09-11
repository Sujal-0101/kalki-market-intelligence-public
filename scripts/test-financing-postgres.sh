#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
image=postgres:18.0-alpine3.22@sha256:48c8ad3a7284b82be4482a52076d47d879fd6fb084a1cbfccbd551f9331b0e40
container=kalki-financing-postgres-gate-$$
temporary_dir=$(mktemp -d)
cleanup() {
    docker container rm --force "$container" >/dev/null 2>&1 || true
    rm -r -- "$temporary_dir"
}
trap cleanup EXIT HUP INT TERM

printf 'unused-trust-auth-password\n' >"$temporary_dir/password"
docker run --detach --name "$container" --publish 127.0.0.1::5432 \
    --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=768m \
    --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=kalki_test \
    --env POSTGRES_USER=postgres "$image" >/dev/null

attempt=0
consecutive_ready=0
while [ "$consecutive_ready" -lt 3 ]
do
    attempt=$((attempt + 1))
    if docker exec "$container" pg_isready --username postgres --dbname kalki_test \
        >/dev/null 2>&1
    then
        consecutive_ready=$((consecutive_ready + 1))
    else
        consecutive_ready=0
    fi
    if [ "$attempt" -ge 45 ]; then
        echo "Disposable financing database did not become ready." >&2
        exit 1
    fi
    sleep 1
done

docker exec "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username postgres --dbname kalki_test \
    --command "CREATE ROLE kalki_app LOGIN;" >/dev/null
for migration in "$repository_dir"/migrations/00[01][0-9]_*.sql
do
    docker exec --interactive "$container" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
        --username postgres --dbname kalki_test <"$migration" >/dev/null
done

published_port=$(docker port "$container" 5432/tcp | sed 's/^.*://')
KALKI_FINANCING_GATE_PASSWORD_FILE="$temporary_dir/password" \
KALKI_FINANCING_GATE_PORT="$published_port" \
    "$repository_dir/.venv/bin/pytest" -q \
    "$repository_dir/tests/test_financing_postgres_integration.py"

echo "Disposable PostgreSQL financing gate passed."
