"""Administrative command line, used by the installers and operators.

  python -m backend.cli init-db
  python -m backend.cli create-user --username jdoe --display-name "J. Doe" \
      --roles admin --clearance S --citizenship USA
  python -m backend.cli set-system-high S --actor installer
  python -m backend.cli verify-chain

Passwords are always read interactively (never from arguments or files).
"""

from __future__ import annotations

import argparse
import getpass
import glob
import os
import sys

from backend.db.database import get_engine, get_session
from backend.models import governance as _gov  # noqa: F401 (register tables)
from backend.models import schema


def init_db() -> None:
    engine = get_engine()
    if engine.dialect.name == "postgresql":
        here = os.path.join(os.path.dirname(__file__), "db", "migrations")
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS schema_migrations "
                                 "(name text PRIMARY KEY, applied_at timestamptz DEFAULT now())")
            done = {r[0] for r in conn.exec_driver_sql("SELECT name FROM schema_migrations")}
            for path in sorted(glob.glob(os.path.join(here, "*.sql"))):
                name = os.path.basename(path)
                if name in done:
                    continue
                with open(path, encoding="utf-8") as fh:
                    conn.exec_driver_sql(fh.read())
                conn.exec_driver_sql("INSERT INTO schema_migrations (name) VALUES (%s)", (name,))
                print("applied", name)
    else:
        schema.Base.metadata.create_all(engine)
        print("sqlite schema created")


def _session():
    gen = get_session()
    return gen, next(gen)


def create_user(args) -> None:
    from fastapi import HTTPException
    from backend.api.users import UserIn, create_user as _create
    pw = None
    if args.auth_source == "local":
        pw = getpass.getpass("Initial password: ")
        if pw != getpass.getpass("Confirm password: "):
            sys.exit("passwords do not match")
    gen, db = _session()
    try:
        user = _create(db, UserIn(
            username=args.username, display_name=args.display_name,
            auth_source=args.auth_source, initial_password=pw,
            roles=args.roles.split(","), clearance=args.clearance,
            citizenship=args.citizenship,
            compartments=[c for c in (args.compartments or "").split(",") if c],
            need_to_know_groups=[g for g in (args.ntk or "").split(",") if g]),
            actor="cli:" + getpass.getuser())
        db.commit()
        print("created", user.username, user.id)
    except HTTPException as exc:
        db.rollback()
        sys.exit("error: {}".format(exc.detail))
    finally:
        gen.close()


def set_system_high(args) -> None:
    from backend.policy import store
    gen, db = _session()
    try:
        cur = store.current(db)
        new = dict(cur.settings, system_high=args.level.upper())
        store.update(db, actor=args.actor, settings=new,
                     justification=args.justification or
                     "System high set at installation by the system administrator")
        db.commit()
        print("system high set to", args.level.upper())
    finally:
        gen.close()


def verify_chain(_args) -> None:
    from backend.governance import chain
    gen, db = _session()
    try:
        ok, bad, n = chain.verify(db)
        print("governance chain {} ({} events checked{})".format(
            "INTACT" if ok else "BROKEN", n, "" if ok else ", first bad seq {}".format(bad)))
        sys.exit(0 if ok else 2)
    finally:
        gen.close()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="ragmt")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    cu = sub.add_parser("create-user")
    cu.add_argument("--username", required=True)
    cu.add_argument("--display-name", required=True)
    cu.add_argument("--roles", required=True, help="comma-separated")
    cu.add_argument("--clearance", required=True)
    cu.add_argument("--citizenship", required=True)
    cu.add_argument("--compartments")
    cu.add_argument("--ntk")
    cu.add_argument("--auth-source", default="local")
    sh = sub.add_parser("set-system-high")
    sh.add_argument("level")
    sh.add_argument("--actor", default="installer")
    sh.add_argument("--justification")
    sub.add_parser("verify-chain")
    args = ap.parse_args(argv)
    {"init-db": lambda a: init_db(), "create-user": create_user,
     "set-system-high": set_system_high, "verify-chain": verify_chain}[args.cmd](args)


if __name__ == "__main__":
    main()
