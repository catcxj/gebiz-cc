from __future__ import annotations

from fastapi import Header
from typing import Annotated


def current_user_id(x_user_id: Annotated[str | None, Header()] = None) -> str:
    """
    Minimal user identification: trust a header for now (single-tenant on-prem).
    Swap for real SSO/auth later — PRD hasn't specified the mechanism.
    """
    return x_user_id or "default"
