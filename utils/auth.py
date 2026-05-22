"""
utils/auth.py — Identity and budget management.

Auth uses a manual Google OAuth 2.0 code flow via plain HTTP requests,
bypassing Streamlit's built-in OAuth infrastructure entirely.

Flow:
  1. render_email_gate() shows a "Sign in with Google" link.
  2. Google redirects back to GOOGLE_REDIRECT_URI with ?code=... in the URL.
  3. On the next render, the code is detected via st.query_params and exchanged
     for user info using Google's token + userinfo endpoints.
  4. The verified @accedo.tv email is stored in session_state.
"""

import logging
import os
import time
import urllib.parse
from typing import Optional

import requests
import streamlit as st

import config

logger = logging.getLogger("ott_lead_gen.auth")

_GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
_SCOPES              = "openid email profile"


def _cfg(key: str, default: str = "") -> str:
    # Try st.secrets first (Streamlit Cloud), then env vars
    try:
        val = st.secrets[key]
        if val:
            return val
    except KeyError:
        pass
    except Exception as exc:
        logger.warning("st.secrets access error for %s: %s", key, exc)
    return os.environ.get(key, default)


def _build_auth_url() -> str:
    client_id    = _cfg("GOOGLE_CLIENT_ID")
    redirect_uri = _cfg("GOOGLE_REDIRECT_URI", "http://localhost:8501/")

    if not client_id:
        st.error(
            "**Configuration error:** `GOOGLE_CLIENT_ID` is not set in Streamlit secrets. "
            "Please add it under Settings → Secrets in the Streamlit Cloud dashboard.",
            icon="🔑",
        )
        st.stop()

    params = {
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         _SCOPES,
        "hd":            "accedo.tv",
        "access_type":   "online",
        "prompt":        "select_account",
    }
    return _GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


def _exchange_code(code: str) -> Optional[dict]:
    """Exchange an authorization code for Google user info."""
    try:
        token_resp = requests.post(_GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     _cfg("GOOGLE_CLIENT_ID"),
            "client_secret": _cfg("GOOGLE_CLIENT_SECRET"),
            "redirect_uri":  _cfg("GOOGLE_REDIRECT_URI", "http://localhost:8501/"),
            "grant_type":    "authorization_code",
        }, timeout=10)
        if not token_resp.ok:
            logger.error("Token exchange failed: %s %s", token_resp.status_code, token_resp.text)
            return None
        access_token = token_resp.json().get("access_token")
        if not access_token:
            return None
        userinfo_resp = requests.get(
            _GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        return userinfo_resp.json() if userinfo_resp.ok else None
    except Exception as exc:
        logger.error("OAuth exchange error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def get_current_user() -> Optional[str]:
    """Return the authenticated user's email, or None if not signed in."""
    return st.session_state.get("user_email") or None


def require_user() -> str:
    """Return current user or stop with a prompt."""
    user = get_current_user()
    if not user:
        st.warning("Please sign in to continue.")
        st.stop()
    return user


def render_email_gate() -> bool:
    """
    Enforce Google OAuth sign-in restricted to @accedo.tv accounts.
    Returns True if authenticated, False if the gate is showing (app should stop).
    Call this at the very top of the main app body.
    """
    # ---- Handle OAuth callback (Google redirected back with ?code=...) ----
    if "code" in st.query_params:
        code = st.query_params["code"]
        st.query_params.clear()

        with st.spinner("Completing sign-in..."):
            user_info = _exchange_code(code)

        if not user_info:
            st.error("Sign-in failed. Please try again.")
            return False

        email = (user_info.get("email") or "").strip().lower()
        if not email.endswith("@accedo.tv"):
            _, col, _ = st.columns([1, 2, 1])
            with col:
                st.error(f"Access restricted to @accedo.tv accounts. You signed in as **{email}**.")
            return False

        st.session_state["user_email"]        = email
        st.session_state["selected_director"] = email
        st.rerun()

    # ---- Already authenticated ----
    if st.session_state.get("user_email"):
        return True

    # ---- Sign-in gate ----
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown("## 🎯 Accedo Lead Scout")
        st.markdown("---")
        st.markdown("Sign in with your Accedo Google account to continue.")
        auth_url = _build_auth_url()
        # target="_self" keeps OAuth in the same tab so the callback lands correctly
        st.markdown(
            f'<a href="{auth_url}" target="_self" style="display:block;text-decoration:none;">'
            f'<div style="background:#4285F4;color:#fff;text-align:center;padding:10px 24px;'
            f'border-radius:4px;font-size:16px;cursor:pointer;font-family:sans-serif;'
            f'font-weight:500;margin-top:8px;">Sign in with Google</div></a>',
            unsafe_allow_html=True,
        )
    return False


# ---------------------------------------------------------------------------
# Budget management
# ---------------------------------------------------------------------------

def get_month_spend(director: str, sheets_client=None) -> float:
    """Return total USD spent by director in the current calendar month, cached 5 min."""
    cache_key    = f"budget_spend_{director}"
    cache_ts_key = f"budget_spend_ts_{director}"
    now = time.monotonic()

    if (cache_key in st.session_state and
            now - st.session_state.get(cache_ts_key, 0) < 300):
        return st.session_state[cache_key]

    if not director or not sheets_client:
        return 0.0

    try:
        rows   = sheets_client.get_director_month_spend(director)
        result = round(sum(rows), 4)
        st.session_state[cache_key]    = result
        st.session_state[cache_ts_key] = now
        return result
    except Exception as exc:
        logger.warning("Auth: could not load spend for %s: %s", director, exc)
        return st.session_state.get(cache_key, 0.0)


def get_budget_remaining(director: str, sheets_client=None) -> float:
    spent = get_month_spend(director, sheets_client)
    return round(config.DIRECTOR_BUDGET_USD - spent, 4)


def is_over_budget(director: str, sheets_client=None) -> bool:
    return get_budget_remaining(director, sheets_client) <= 0


def render_budget_bar(director: str, sheets_client=None) -> None:
    """Render a budget progress bar in the sidebar."""
    if not director:
        return

    spent     = get_month_spend(director, sheets_client)
    budget    = config.DIRECTOR_BUDGET_USD
    pct       = min(spent / budget, 1.0) if budget > 0 else 0
    remaining = max(budget - spent, 0)

    colour = "🟢" if pct < 0.6 else "🟡" if pct < 0.85 else "🔴"
    st.caption(
        f"{colour} **${spent:.2f}** of **${budget:.2f}** used this month  \n"
        f"${remaining:.2f} remaining"
    )
    st.progress(pct)
