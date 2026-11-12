from __future__ import annotations

import pytest
from manga_common.errors import RateLimitError
from services.gateway.app import api


def test_admin_login_limiter_counts_failures() -> None:
    ip = "198.51.100.77"
    api._admin_failures.pop(ip, None)
    for _ in range(4):
        api._record_admin_failure(ip)
    api._check_admin_login_rate(ip)
    api._record_admin_failure(ip)
    with pytest.raises(RateLimitError):
        api._check_admin_login_rate(ip)
    api._admin_failures.pop(ip, None)
