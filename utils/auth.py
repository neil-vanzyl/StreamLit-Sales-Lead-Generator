"""
utils/auth.py — Identity and budget management.

Today: honour-system dropdown stored in session state.
Future: replace get_current_user() body with OAuth/JWT token lookup.
Nothing else in the codebase needs to change when auth method switches.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import streamlit as st

import config

logger = logging.getLogger("ott_lead_gen.auth")


# ---------------------------------------------------------------------------
# Identity — swap this function body when moving to SSO
# ---------------------------------------------------------------------------

def get_current_user() -> Optional[str]:
    """
    Return the currently selected sales director name.
    Returns None if no valid director is selected.

    MIGRATION PATH TO SSO:
    Replace the body of this function with:
        token = st.experimental_get_query_params().get("token", [None])[0]
        return verify_jwt(token)  # or Google OAuth callback
    Everything else — budget checks, Sheets writes, UI — calls this function
    and never needs to change.
    """
    director = st.session_state.get("selected_director", "")
    if not director or director == config.SALES_DIRECTORS[0]:
        return None
    return director


def require_user() -> str:
    """
    Return current user or stop the app with a prompt to select a name.
    Use at the top of any pipeline run handler.
    """
    user = get_current_user()
    if not user:
        st.warning("⚠️ Please select your name in the sidebar before running.")
        st.stop()
    return user


# ---------------------------------------------------------------------------
# Budget management
# ---------------------------------------------------------------------------

def get_month_spend(director: str, sheets_client=None) -> float:
    import streamlit as st
    import time
    cache_key = f"budget_spend_{director}"
    cache_ts_key = f"budget_spend_ts_{director}"
    now = time.monotonic()
    
    # Cache for 5 minutes
    if (cache_key in st.session_state and 
        now - st.session_state.get(cache_ts_key, 0) < 300):
        return st.session_state[cache_key]
    
    if not director or not sheets_client:
        return 0.0
    try:
        rows = sheets_client.get_director_month_spend(director)
        result = round(sum(rows), 4)
        st.session_state[cache_key] = result
        st.session_state[cache_ts_key] = now
        return result
    except Exception as exc:
        logger.warning(f"Auth: could not load spend for {director}: {exc}")
        return st.session_state.get(cache_key, 0.0)


def get_budget_remaining(director: str, sheets_client=None) -> float:
    """Return remaining budget in USD for this director this month."""
    spent = get_month_spend(director, sheets_client)
    return round(config.DIRECTOR_BUDGET_USD - spent, 4)


def is_over_budget(director: str, sheets_client=None) -> bool:
    return get_budget_remaining(director, sheets_client) <= 0


def render_budget_bar(director: str, sheets_client=None) -> None:
    """
    Render a budget progress bar in the sidebar.
    Call this from the sidebar section of gui.py.
    """
    if not director or director == config.SALES_DIRECTORS[0]:
        return

    spent    = get_month_spend(director, sheets_client)
    budget   = config.DIRECTOR_BUDGET_USD
    pct      = min(spent / budget, 1.0) if budget > 0 else 0
    remaining = max(budget - spent, 0)

    colour = "🟢" if pct < 0.6 else "🟡" if pct < 0.85 else "🔴"
    st.caption(
        f"{colour} **${spent:.2f}** of **${budget:.2f}** used this month  \n"
        f"${remaining:.2f} remaining"
    )
    st.progress(pct)