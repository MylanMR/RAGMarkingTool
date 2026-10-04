#!/usr/bin/env bash
# Stage an offline Linux bundle (x86_64, glibc 2.28+: RHEL/Rocky/Alma 8+,
# Ubuntu 20.04+). Run on a connected build host of the same distro family
# as the target. Builds PostgreSQL 16 and pgvector from source into a
# relocatable prefix so the target needs no package repositories.
set -euo pipefail
OUT="${1:-./ragmt-bundle-linux}"
PY_STANDALONE_URL="${PY_STANDALONE_URL:-https://github.com/indygreg/python-build-standalone/releases/download/20241016/cpython-3.12.7+20241016-x86_64-unknown-linux-gnu-install_only.tar.gz}"
PG_VERSION="${PG_VERSION:-16.4}"
PGVECTOR_VERSION="${PGVECTOR_VERSION:-0.7.4}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

curl -fsSL "$PY_STANDALONE_URL" -o "$OUT/python.tar.gz"
curl -fsSL "https://ftp.postgresql.org/pub/source/v${PG_VERSION}/postgresql-${PG_VERSION}.tar.bz2" -o "$WORK/pg.tar.bz2"
curl -fsSL "https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz" -o "$WORK/pgvector.tar.gz"

# PostgreSQL + pgvector into /opt/ragmt/pgsql (relocatable via the install path)
tar -xjf "$WORK/pg.tar.bz2" -C "$WORK"
( cd "$WORK/postgresql-${PG_VERSION}" && ./configure --prefix=/opt/ragmt/pgsql --with-openssl --without-icu \
    && make -j"$(nproc)" && make install DESTDIR="$WORK/stage" )
tar -xzf "$WORK/pgvector.tar.gz" -C "$WORK"
( cd "$WORK/pgvector-${PGVECTOR_VERSION}" && make PG_CONFIG="$WORK/stage/opt/ragmt/pgsql/bin/pg_config" OPTFLAGS="" \
    && make install PG_CONFIG="$WORK/stage/opt/ragmt/pgsql/bin/pg_config" DESTDIR="$WORK/stage" )
# pgvector's install writes to the DESTDIR-prefixed path reported by pg_config
tar -czf "$OUT/pgsql.tar.gz" -C "$WORK/stage/opt/ragmt" pgsql

# Python dependencies installed into a folder for the target interpreter
mkdir -p "$WORK/py" && tar -xzf "$OUT/python.tar.gz" -C "$WORK/py"
grep -v -E '^pyspnego\[kerberos\]' "$REPO/requirements.txt" > "$WORK/req.txt"
"$WORK/py/python/bin/python3" -m pip install --target "$OUT/pylib" --only-binary=:all: -r "$WORK/req.txt"
# gssapi and krb5 ship no manylinux wheels: compile against the build host's
# MIT Kerberos headers (krb5-devel / libkrb5-dev). Targets need libkrb5 and
# libgssapi_krb5 at runtime (present on RHEL and Ubuntu by default).
"$WORK/py/python/bin/python3" -m pip install --target "$OUT/pylib" --no-deps gssapi krb5
rm -rf "$OUT"/pylib/pytest* "$OUT"/pylib/_pytest

( cd "$REPO/frontend" && npm ci && npm run build )
mkdir -p "$OUT/app"
cp -r "$REPO/backend" "$OUT/app/backend"; cp -r "$REPO/frontend/dist" "$OUT/app/ui"
find "$OUT/app" -name __pycache__ -prune -exec rm -rf {} +
cp -r "$REPO/installer/common" "$OUT/common"
cp "$REPO"/installer/linux/{install.sh,ragmt.service,ragmt-postgres.service} "$OUT/"

( cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
echo "Bundle staged at $OUT. SHA-256 of the manifest for transfer paperwork:"
sha256sum "$OUT/SHA256SUMS"
