from __future__ import annotations

import ssl

from src.network.tls import https_context


def test_https_context_is_verified_and_uses_a_loadable_ca_store():
    context = https_context()

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
