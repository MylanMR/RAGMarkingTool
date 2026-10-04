"""Production launcher used by the Windows service and the systemd unit.

Reads RAGMT_* settings from the environment (the service manager loads the
installer-written ragmt.env). TLS is required unless the service binds to
loopback only, in which case a site reverse proxy terminates TLS.
"""

import os
import sys


def main() -> None:
    import uvicorn
    host = os.environ.get("RAGMT_BIND", "127.0.0.1")
    port = int(os.environ.get("RAGMT_PORT", "8443"))
    cert = os.environ.get("RAGMT_TLS_CERT", "")
    key = os.environ.get("RAGMT_TLS_KEY", "")
    if host not in ("127.0.0.1", "::1", "localhost") and not (cert and key):
        sys.exit("refusing to bind {} without RAGMT_TLS_CERT and RAGMT_TLS_KEY".format(host))
    if os.environ.get("RAGMT_DEV") == "1":
        sys.exit("refusing to start the production launcher with RAGMT_DEV=1")
    kwargs = {}
    if cert and key:
        kwargs = {"ssl_certfile": cert, "ssl_keyfile": key}
    uvicorn.run("backend.main:app", host=host, port=port, proxy_headers=False,
                server_header=False, log_level="info", **kwargs)


if __name__ == "__main__":
    main()
