import re
from dataclasses import asdict

import streamlit as st
from pydantic import ValidationError

from github_analyser.analytics import Analytics, build_analytics
from github_analyser.charts import (
    activity_chart,
    age_chart,
    documentation_chart,
    language_chart,
    stars_chart,
)
from github_analyser.config import Settings
from github_analyser.github_client import GitHubAnalyserError, fetch_profile_and_repos
from github_analyser.limits import DailyLimit
from github_analyser.llm import build_reviewer
from github_analyser.scoring import Score
from github_analyser.workflow import run_review

st.set_page_config(page_title="Repo-Lens", page_icon="🧭", layout="centered")

USERNAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
PROFILE_TTL_SECONDS = 3600
REVIEW_TTL_SECONDS = 86400

# One cache entry per username, shared by all visitors. Used unless a visitor skips it.
load_github_data = st.cache_data(ttl=PROFILE_TTL_SECONDS, show_spinner=False)(fetch_profile_and_repos)


@st.cache_resource
def review_budget(limit: int) -> DailyLimit:
    """One daily counter, shared by every visitor of this running app."""
    return DailyLimit(limit)


@st.cache_data(ttl=REVIEW_TTL_SECONDS, show_spinner=False)
def review_cached(data_json: str, _reviewer, _budget: DailyLimit):
    """
    Runs only on a cache miss, so each real LLM call uses one unit of the daily budget
    and a cached review costs nothing. The key is the exact JSON sent to the model, so the
    same numbers always get the same cached review. Arguments starting with _ are not hashed.
    """
    _budget.take()
    return _reviewer.invoke({"data": data_json})


class CachedReviewer:
    """Same .invoke() as the LangChain reviewer, so the workflow does not need to know about the cache."""

    def __init__(self, reviewer, budget: DailyLimit):
        self._reviewer = reviewer
        self._budget = budget

    def invoke(self, inputs: dict):
        return review_cached(inputs["data"], self._reviewer, self._budget)


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as error:
        missing = ", ".join(str(problem["loc"][0]).upper() for problem in error.errors())
        st.error(f"Missing or empty setting(s): {missing}. Copy .env.example to .env and fill them in.")
        st.stop()


def analyse(username: str, settings: Settings, skip_cache: bool) -> dict:
    if skip_cache:
        # Fresh data for this request only. The shared cache is left untouched for everyone else.
        profile, repos = fetch_profile_and_repos(settings.github_token, username)
    else:
        profile, repos = load_github_data(settings.github_token, username)

    analytics = build_analytics(repos)
    budget = review_budget(settings.daily_review_limit)
    reviewer = CachedReviewer(build_reviewer(settings), budget)
    return run_review(profile, analytics, reviewer)


def show_review(result: dict) -> None:
    report = result.get("report")
    if report is None:
        st.warning(result.get("error") or "No AI review: this account has no original public repositories.")
        return

    if result["provider"] == "Gemini":
        st.caption("Review written by Gemini.")
    else:
        st.caption(f"Review written by {result['provider']}, because Gemini was unavailable.")

    st.write(report.overall_summary)

    strengths, weaknesses = st.columns(2)
    with strengths:
        st.markdown("**Strengths**")
        for item in report.strengths:
            st.markdown(f"- {item}")
    with weaknesses:
        st.markdown("**Areas for improvement**")
        for item in report.weaknesses:
            st.markdown(f"- {item}")

    st.markdown("**Recommendations**")
    for item in report.recommendations:
        st.markdown(f"- {item}")

    if report.project_insights:
        st.markdown("**Project insights**")
        for insight in report.project_insights:
            st.markdown(f"- **{insight.repo_name}**: {insight.comment}")

    st.markdown("**Action plan**")
    for number, step in enumerate(report.action_plan, start=1):
        st.markdown(f"{number}. {step}")


def show_score(score: Score) -> None:
    for category in score.categories:
        st.write(f"**{category.name}**: {category.points} / {category.max_points}")
        st.progress(min(category.points / category.max_points, 1.0))
        st.caption(", ".join(f"{part}: {points}" for part, points in category.parts.items()))


def show_charts(analytics: Analytics) -> None:
    if not analytics.facts.original_repos:
        st.info("This account has no original public repositories to chart.")
        return
    for chart in (language_chart, stars_chart, activity_chart, age_chart, documentation_chart):
        st.plotly_chart(chart(analytics))


def show_result(result: dict) -> None:
    profile, analytics, score = result["profile"], result["analytics"], result["score"]
    facts = analytics.facts

    picture, who, total = st.columns([1, 4, 2])
    picture.image(profile.avatar_url, width=72)
    who.subheader(profile.name or profile.username)
    if profile.bio:
        who.write(profile.bio)
    total.metric("GitHub score", f"{score.total} / {score.max_total}")

    cards = st.columns(4)
    cards[0].metric("Own repositories", facts.original_repos)
    cards[1].metric("Followers", profile.followers)
    cards[2].metric("Following", profile.following)
    cards[3].metric("Stars on own repos", facts.total_stars)
    if facts.forked_repos:
        st.caption(f"{facts.forked_repos} forked repositories are left out of the score and the numbers above.")

    review_tab, score_tab, charts_tab, data_tab = st.tabs(["AI review", "Score", "Charts", "Raw data"])
    with review_tab:
        show_review(result)
    with score_tab:
        show_score(score)
    with charts_tab:
        show_charts(analytics)
    with data_tab:
        st.json(asdict(facts))
        st.dataframe(analytics.originals)


def main() -> None:
    st.title("Repo-Lens")
    st.caption("Enter a GitHub username to get a score, charts and an AI review.")
    settings = load_settings()

    username = st.text_input("GitHub username", placeholder="e.g. torvalds").strip()
    analyse_column, cache_column = st.columns(2)
    clicked = analyse_column.button("Analyse", type="primary")
    skip_cache = cache_column.checkbox("Skip the cache")

    if clicked:
        if not USERNAME_PATTERN.fullmatch(username):
            st.warning("Enter just the username, for example: torvalds")
        else:
            try:
                with st.spinner("Reading GitHub and writing the review..."):
                    st.session_state["result"] = analyse(username, settings, skip_cache)
            except GitHubAnalyserError as error:
                st.session_state.pop("result", None)
                st.error(str(error))

    if "result" in st.session_state:
        show_result(st.session_state["result"])


main()