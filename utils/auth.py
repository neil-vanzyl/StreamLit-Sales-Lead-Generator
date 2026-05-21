"""
utils/auth.py — Identity and budget management.

Auth is handled via Streamlit's built-in Google OAuth (st.login / st.user).
Only @accedo.tv accounts are permitted. To swap providers, change the
provider name passed to st.login() and update the [auth.<provider>] block
in .streamlit/secrets.toml.
"""

import logging
from typing import Optional

import streamlit as st

import config

logger = logging.getLogger("ott_lead_gen.auth")


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def get_current_user() -> Optional[str]:
    """Return the authenticated user's email, or None if not logged in."""
    user = getattr(st, "user", None)
    if not user or not user.is_logged_in:
        return None
    email = (user.email or "").strip().lower()
    return email if email.endswith("@accedo.tv") else None


def require_user() -> str:
    """Return current user or stop with a prompt."""
    user = get_current_user()
    if not user:
        st.warning("Please sign in to continue.")
        st.stop()
    return user


def render_email_gate() -> bool:
    """
    Enforce Google OAuth login restricted to @accedo.tv accounts.
    Returns True if authenticated, False if the gate is showing (app should stop).
    Call this at the very top of the main app body.
    """
    user = getattr(st, "user", None)

    if not user or not user.is_logged_in:
        _, col, _ = st.columns([1, 2, 1])
        with col:
            st.markdown("## 🎯 Accedo Lead Scout")
            st.markdown("---")
            st.markdown("Sign in with your Accedo Google account to continue.")
            if st.button("Sign in with Google", type="primary", use_container_width=True):
                st.login("google")
        return False

    email = (user.email or "").strip().lower()
    if not email.endswith("@accedo.tv"):
        _, col, _ = st.columns([1, 2, 1])
        with col:
            st.error(f"Access restricted to @accedo.tv accounts. You signed in as **{email}**.")
            if st.button("Sign out", key="wrong_account_signout"):
                st.logout()
        return False

    # Sync selected_director for budget-tracking compatibility
    if not st.session_state.get("selected_director"):
        st.session_state["selected_director"] = email

    return True


# ---------------------------------------------------------------------------
# Budget management
# ---------------------------------------------------------------------------

import time

def get_month_spend(director: str, sheets_client=None) -> float:
    """
    Return total USD spent by this director in the current calendar month.
    Cached for 5 minutes to avoid hammering the Sheets API on every render.
    """
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
        logger.warning(f"Auth: could not load spend for {director}: {exc}")
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
