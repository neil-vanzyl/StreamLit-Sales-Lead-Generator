"""
utils/auth.py — Identity and budget management.

Today: email entry on app load stored in session state.
Future: replace get_current_user() body with OAuth/JWT token lookup.
Nothing else in the codebase needs to change when auth method switches.
"""

import logging
import time
from typing import Optional

import streamlit as st

import config

logger = logging.getLogger("ott_lead_gen.auth")


# ---------------------------------------------------------------------------
# Identity — swap this function body when moving to SSO
# ---------------------------------------------------------------------------

def get_current_user() -> Optional[str]:
    """
    Return the current user's email address.
    Returns None if not yet authenticated.

    MIGRATION PATH TO SSO:
    Replace the body of this function with:
        token = st.experimental_get_query_params().get("token", [None])[0]
        return verify_jwt(token)
    Everything else calls this function and never needs to change.
    """
    return st.session_state.get("user_email") or None


def require_user() -> str:
    """Return current user or stop with a prompt."""
    user = get_current_user()
    if not user:
        st.warning("Please enter your email address to continue.")
        st.stop()
    return user


def render_email_gate() -> bool:
    """
    Show an email entry gate on app load if the user hasn't identified themselves.
    Returns True if the user is authenticated, False if the gate is showing.
    Call this at the very top of the main app body.
    """
    if st.session_state.get("user_email"):
        return True

    # Centre the gate with columns
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown("## 🎯 Accedo Lead Scout")
        st.markdown("---")
        st.markdown("Enter your email address to continue.")

        with st.form("email_gate_form"):
            email = st.text_input(
                "Work email",
                placeholder="you@accedo.tv",
                key="email_gate_input",
            )
            submitted = st.form_submit_button(
                "Continue →",
                use_container_width=True,
                type="primary",
            )

        if submitted:
            email = email.strip().lower()
            if not email or "@" not in email:
                st.error("Please enter a valid email address.")
            elif not email.endswith("@accedo.tv"):
                st.error("Please enter your Accedo email address (@accedo.tv).")
            else:
                st.session_state["user_email"]       = email
                st.session_state["selected_director"] = email
                st.rerun()

    return False


# ---------------------------------------------------------------------------
# Budget management
# ---------------------------------------------------------------------------

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