"""Minimal authenticated BigQuant data query for local VS Code development."""

from __future__ import annotations

import os

import bigquant
from bigquant import dai


PROXY_ENVIRONMENT_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def main() -> None:
    # A VS Code kernel launched while a VPN was active can retain a stale proxy
    # address. BigQuant's HTTPS client then fails before TLS is established.
    removed_proxies = [key for key in PROXY_ENVIRONMENT_KEYS if os.environ.pop(key, None)]
    # Also bypass a macOS system proxy for this small verification request.
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    print("Network proxy bypass: enabled", flush=True)
    if removed_proxies:
        print(f"Cleared inherited proxy settings: {', '.join(removed_proxies)}", flush=True)

    # Reload AK/SK explicitly so a long-running IDE/kernel does not retain the
    # unauthenticated client state created before `bq auth configure`.
    bigquant.init_from_config()
    print("BigQuant authentication: OK", flush=True)
    result = dai.query(
        """
        SELECT date, instrument, open, high, low, close, volume
        FROM cn_stock_bar1d
        WHERE date >= '2024-01-02' AND date <= '2024-01-05'
        ORDER BY date, instrument
        LIMIT 10
        """,
        filters={"date": ["2024-01-02", "2024-01-05"]},
        use_studio=True,
    )
    print(f"Query result type: {type(result).__name__}", flush=True)
    print(result.df())


if __name__ == "__main__":
    main()
