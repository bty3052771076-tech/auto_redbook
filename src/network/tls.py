"""TLS helpers for Python environments with incomplete system CA paths.

Some Windows Python installations expose OpenSSL default paths that do not
exist on disk.  ``urllib`` then raises ``FileNotFoundError`` during the TLS
handshake instead of returning a useful HTTP error.  The project already
depends on ``certifi`` in the workspace virtual environment, so use that local
bundle when the system paths are unavailable.
"""

from __future__ import annotations

import os
from pathlib import Path
import ssl


def ensure_ssl_ca_bundle() -> str:
    """Return a usable CA bundle and make it the process default when needed."""

    configured_file = str(os.getenv("SSL_CERT_FILE") or "").strip()
    configured_dir = str(os.getenv("SSL_CERT_DIR") or "").strip()
    if configured_file and Path(configured_file).is_file():
        return configured_file
    if configured_dir and Path(configured_dir).is_dir():
        return configured_dir

    defaults = ssl.get_default_verify_paths()
    if defaults.cafile and Path(defaults.cafile).is_file():
        return str(defaults.cafile)
    if defaults.capath and Path(defaults.capath).is_dir():
        return str(defaults.capath)

    try:
        import certifi

        bundle = Path(certifi.where())
    except Exception:
        return ""
    if not bundle.is_file():
        return ""

    os.environ["SSL_CERT_FILE"] = str(bundle)
    os.environ.pop("SSL_CERT_DIR", None)
    return str(bundle)


def https_context() -> ssl.SSLContext:
    """Build a verified HTTPS context using the workspace CA bundle if needed."""

    bundle = ensure_ssl_ca_bundle()
    if bundle and Path(bundle).is_file():
        return ssl.create_default_context(cafile=bundle)
    return ssl.create_default_context()
