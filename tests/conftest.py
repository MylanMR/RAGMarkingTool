import os
os.environ.setdefault("RAGMT_DEV", "1")
os.environ.setdefault("RAGMT_AUTH_MODE", "scaffold")
import backend.models.governance  # noqa: F401
