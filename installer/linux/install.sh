#!/usr/bin/env bash
# Install the RAG Marking Tool from an offline bundle. Run as root from the
# bundle directory:
#   sudo ./install.sh --system-high S [--bind 0.0.0.0 --tls-cert c.pem --tls-key k.pem]
#                     [--enclave-cidrs 10.0.0.0/8] [--enclave-hosts llm.local] [--ca-bundle dod.pem]
set -euo pipefail
PREFIX=/opt/ragmt; DATA=/var/lib/ragmt; ETC=/etc/ragmt
BIND=127.0.0.1; PORT=8443; PGPORT=54329
SYSTEM_HIGH=""; TLS_CERT=""; TLS_KEY=""; CIDRS=""; HOSTS=""; CA=""
AD_REALM=""; AD_SPN_HOST=""; AD_KEYTAB=""; AD_SOURCE="tool"; AD_LDAP_URL=""; AD_BASE_DN=""; AD_GROUP_MAP=""
while [[ $# -gt 0 ]]; do case "$1" in
  --system-high) SYSTEM_HIGH="$2"; shift 2;; --bind) BIND="$2"; shift 2;; --port) PORT="$2"; shift 2;;
  --tls-cert) TLS_CERT="$2"; shift 2;; --tls-key) TLS_KEY="$2"; shift 2;;
  --enclave-cidrs) CIDRS="$2"; shift 2;; --enclave-hosts) HOSTS="$2"; shift 2;; --ca-bundle) CA="$2"; shift 2;;
  --ad-realm) AD_REALM="$2"; shift 2;; --ad-spn-host) AD_SPN_HOST="$2"; shift 2;; --ad-keytab) AD_KEYTAB="$2"; shift 2;;
  --ad-attribute-source) AD_SOURCE="$2"; shift 2;; --ad-ldap-url) AD_LDAP_URL="$2"; shift 2;;
  --ad-base-dn) AD_BASE_DN="$2"; shift 2;; --ad-group-map) AD_GROUP_MAP="$2"; shift 2;;
  *) echo "unknown option $1" >&2; exit 2;; esac; done
[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
[[ "$SYSTEM_HIGH" =~ ^(U|C|S|TS|TS/SCI)$ ]] || { echo "--system-high U|C|S|TS|TS/SCI is required" >&2; exit 2; }
if [[ "$BIND" != "127.0.0.1" && ( -z "$TLS_CERT" || -z "$TLS_KEY" ) ]]; then
  echo "binding $BIND requires --tls-cert and --tls-key" >&2; exit 2; fi
if [[ -n "$AD_REALM" && ( -z "$AD_SPN_HOST" || -z "$AD_KEYTAB" ) ]]; then
  echo "--ad-realm requires --ad-spn-host and --ad-keytab" >&2; exit 2; fi
cd "$(dirname "$0")"

echo "Verifying bundle integrity"; sha256sum --quiet -c SHA256SUMS

secret() { head -c 32 /dev/urandom | base64 | tr -d '+/=' | head -c 40; }
id ragmt >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin ragmt
id ragmt-pg >/dev/null 2>&1 || useradd --system --home-dir "$DATA/pgdata" --shell /usr/sbin/nologin ragmt-pg

install -d -m 0755 "$PREFIX" && install -d -m 0750 "$ETC" && install -d -m 0750 -o ragmt "$DATA" "$DATA/logs"
install -d -m 0700 -o ragmt-pg "$DATA/pgdata"
tar -xzf python.tar.gz -C "$PREFIX"              # -> $PREFIX/python
tar -xzf pgsql.tar.gz -C "$PREFIX"               # -> $PREFIX/pgsql
rm -rf "$PREFIX/pylib" "$PREFIX/app"; cp -r pylib app common "$PREFIX/"
chown -R root:root "$PREFIX"; chmod -R go-w "$PREFIX"

PG="$PREFIX/pgsql/bin"; PY="$PREFIX/python/bin/python3"
SUPER_PW="$(secret)"; OWNER_PW="$(secret)"; APP_PW="$(secret)"
PWF="$(mktemp)"; chown ragmt-pg "$PWF"; printf '%s' "$SUPER_PW" > "$PWF"
runuser -u ragmt-pg -- "$PG/initdb" -D "$DATA/pgdata" -U postgres --pwfile="$PWF" -A scram-sha-256 -E UTF8 --locale=C
rm -f "$PWF"
cat >> "$DATA/pgdata/postgresql.conf" <<CONF
listen_addresses = '127.0.0.1'
port = $PGPORT
password_encryption = 'scram-sha-256'
unix_socket_directories = '$DATA/pgdata'
log_connections = on
log_disconnections = on
CONF
echo "host all all 127.0.0.1/32 scram-sha-256" > "$DATA/pgdata/pg_hba.conf"

sed -e "s#@PREFIX@#$PREFIX#g" -e "s#@DATA@#$DATA#g" ragmt-postgres.service > /etc/systemd/system/ragmt-postgres.service
sed -e "s#@PREFIX@#$PREFIX#g" -e "s#@DATA@#$DATA#g" -e "s#@ETC@#$ETC#g" ragmt.service > /etc/systemd/system/ragmt.service
systemctl daemon-reload && systemctl enable --now ragmt-postgres

export PGPASSWORD="$SUPER_PW"
for i in $(seq 1 20); do "$PG/pg_isready" -h 127.0.0.1 -p "$PGPORT" -q && break; sleep 1; done
"$PG/psql" -h 127.0.0.1 -p "$PGPORT" -U postgres -v ON_ERROR_STOP=1 \
  -c "CREATE ROLE ragmt_owner LOGIN PASSWORD '$OWNER_PW';" -c "CREATE ROLE ragmt_app LOGIN PASSWORD '$APP_PW';" \
  -c "CREATE DATABASE ragmt OWNER ragmt_owner;" -c "REVOKE ALL ON DATABASE ragmt FROM PUBLIC;" \
  -c "GRANT CONNECT ON DATABASE ragmt TO ragmt_app;"
"$PG/psql" -h 127.0.0.1 -p "$PGPORT" -U postgres -d ragmt -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;"

export PYTHONPATH="$PREFIX/pylib:$PREFIX/app"
export DATABASE_URL="postgresql+psycopg2://ragmt_owner:$OWNER_PW@127.0.0.1:$PGPORT/ragmt"
( cd "$PREFIX/app" && "$PY" -m backend.cli init-db )
export PGPASSWORD="$OWNER_PW"
"$PG/psql" -h 127.0.0.1 -p "$PGPORT" -U ragmt_owner -d ragmt -v ON_ERROR_STOP=1 -f "$PREFIX/common/roles.sql"
( cd "$PREFIX/app" && "$PY" -m backend.cli set-system-high "$SYSTEM_HIGH" --actor "installer:${SUDO_USER:-root}" )
unset PGPASSWORD

umask 077
printf 'postgres=%s\nragmt_owner=%s\n' "$SUPER_PW" "$OWNER_PW" > "$ETC/db-admin.secret"
cat > "$ETC/ragmt.env" <<ENV
DATABASE_URL=postgresql+psycopg2://ragmt_app:$APP_PW@127.0.0.1:$PGPORT/ragmt
VECTOR_STORE=pgvector
RAGMT_AUTH_MODE=production
RAGMT_BIND=$BIND
RAGMT_PORT=$PORT
RAGMT_TLS_CERT=$TLS_CERT
RAGMT_TLS_KEY=$TLS_KEY
RAGMT_ENCLAVE_CIDRS=$CIDRS
RAGMT_ENCLAVE_HOSTS=$HOSTS
RAGMT_CA_BUNDLE=$CA
RAGMT_FRONTEND_DIST=$PREFIX/app/ui
PYTHONPATH=$PREFIX/pylib:$PREFIX/app
ENV
if [[ -n "$AD_REALM" ]]; then
  install -m 0640 -o root -g ragmt "$AD_KEYTAB" "$ETC/http.keytab"
  [[ -n "$AD_GROUP_MAP" ]] && install -m 0640 -o root -g ragmt "$AD_GROUP_MAP" "$ETC/ad-group-map.json"
  cat >> "$ETC/ragmt.env" <<ENV
RAGMT_AD_ENABLED=1
RAGMT_AD_REALM=$AD_REALM
RAGMT_AD_SPN_HOST=$AD_SPN_HOST
KRB5_KTNAME=FILE:$ETC/http.keytab
RAGMT_AD_ATTRIBUTE_SOURCE=$AD_SOURCE
RAGMT_AD_LDAP_URL=$AD_LDAP_URL
RAGMT_AD_LDAP_BASE_DN=$AD_BASE_DN
RAGMT_AD_GROUP_MAP=${AD_GROUP_MAP:+file:$ETC/ad-group-map.json}
ENV
fi
chown root:ragmt "$ETC/ragmt.env"; chmod 0640 "$ETC/ragmt.env"; chmod 0600 "$ETC/db-admin.secret"
[[ -n "$TLS_KEY" ]] && { chgrp ragmt "$TLS_KEY"; chmod 0640 "$TLS_KEY"; }
umask 022

echo; echo "Create the first system administrator account."
read -rp "Admin username: " U; read -rp "Display name: " N; read -rp "Clearance (U/C/S/TS/TS/SCI): " C; read -rp "Citizenship trigraph: " Z
( cd "$PREFIX/app" && "$PY" -m backend.cli create-user --username "$U" --display-name "$N" --roles admin --clearance "$C" --citizenship "$Z" )
echo; echo "Create the first Authorizing Official account (a different person under the default policy)."
read -rp "AO username: " U; read -rp "Display name: " N; read -rp "Clearance: " C; read -rp "Citizenship trigraph: " Z
( cd "$PREFIX/app" && "$PY" -m backend.cli create-user --username "$U" --display-name "$N" --roles ao --clearance "$C" --citizenship "$Z" )

systemctl enable --now ragmt
if [[ "$BIND" != "127.0.0.1" ]] && command -v firewall-cmd >/dev/null; then
  firewall-cmd --permanent --add-port="$PORT/tcp" && firewall-cmd --reload; fi
echo "Installed. Service status: systemctl status ragmt"
