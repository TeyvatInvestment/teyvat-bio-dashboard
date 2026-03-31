"""Patch streamlit-authenticator's CookieModel to use native Streamlit APIs.

Problem: streamlit-authenticator 0.4.2 reads cookies via st.context.cookies (reliable)
but writes them via extra-streamlit-components CookieManager (iframe-based, unreliable).
The iframe approach causes cookies to not persist across page refreshes.

Fix: Replace the CookieModel's set/delete methods with st.html()-based JavaScript
that runs directly in the page (no iframe), ensuring cookies are set reliably.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st
from streamlit_authenticator.models.cookie_model import CookieModel


def _set_cookie_native(self: CookieModel) -> None:
    """Set auth cookie via st.html() — runs JS directly in the page, no iframe."""
    if self.cookie_expiry_days == 0:
        return
    self.exp_date = self._set_exp_date()
    token = self._token_encode()
    expires = (datetime.now() + timedelta(days=self.cookie_expiry_days)).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )
    js = f"""
    <script>
    document.cookie = "{self.cookie_name}={token}; expires={expires}; path=/; SameSite=Strict";
    </script>
    """
    st.html(js)


def _delete_cookie_native(self: CookieModel) -> None:
    """Delete auth cookie via st.html() — runs JS directly in the page, no iframe."""
    js = f"""
    <script>
    document.cookie = "{self.cookie_name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Strict";
    </script>
    """
    st.html(js)


def _get_cookie_native(self: CookieModel):
    """Read auth cookie via st.context.cookies (already native, but skip logout check bug)."""
    if st.session_state.get("logout"):
        return False
    self.token = (
        st.context.cookies[self.cookie_name]
        if self.cookie_name in st.context.cookies
        else None
    )
    if self.token is not None:
        self.token = self._token_decode()
        if (
            self.token is not False
            and "username" in self.token
            and self.token["exp_date"] > datetime.now().timestamp()
        ):
            return self.token
    return None


def patch_cookie_model() -> None:
    """Monkey-patch CookieModel to bypass the iframe-based CookieManager."""
    CookieModel.set_cookie = _set_cookie_native
    CookieModel.delete_cookie = _delete_cookie_native
    CookieModel.get_cookie = _get_cookie_native
