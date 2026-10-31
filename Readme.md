# RepoLens

See your GitHub profile the way a recruiter does, and get a plan to improve it.

**Live app:** https://repo-lens2.streamlit.app/

![RepoLens screenshot](assets/screenshot.png)

Enter a GitHub username. RepoLens reads the public data, scores the profile out of 100 with plain
Python, draws charts, and then asks an LLM to explain the result: strengths, weaknesses,
recommendations and an action plan.

Python works out the facts. The LLM only explains them. It never calculates the score.

## Features

- Profile and repository data from the GitHub API (PyGithub)
- A transparent 0-100 score, with a breakdown for every category and every sub-score
- Forked repositories are left out of every number, so only your own work counts
- Interactive Plotly charts: languages, top repos by stars, last push by month, repo age, documentation coverage
- The AI review comes back as a typed object (Pydantic), not free text
- Gemini writes the review. OpenRouter is an optional backup if Gemini fails
- If every AI model fails, the score and charts still show
- Protection for a public demo: a daily limit on AI reviews, cached reviews, and a hard time limit

## How it works

```
username
   |
   v
GitHub API --> cache (1 hour) --> pandas --> Facts      one fork-free set of numbers
                                               |
                       LangGraph               v
                    +-------------------- scoring --------------------+
                    |                  (plain Python)                  |
                    |                                                  |
            has own repos?                                     no own repos
                    |                                                  |
                    v                                                  v
                 review                                             (skipped)
     cached, daily limit, time budget                                  |
        Gemini, then OpenRouter                                        |
                    |                                                  |
                    +------------------------+-------------------------+
                                             v
                                    Streamlit dashboard
```

- **Facts.** `analytics.py` turns the repo list into one set of numbers. The score, the charts and
  the AI prompt all read the same numbers, so they cannot disagree.
- **Scoring.** `scoring.py` is plain arithmetic. The same data always gives the same score.
- **LangGraph.** The graph has a real branch: an account with no own repositories never costs an
  AI call.
- **The AI review.** Each model call has a hard deadline (12 seconds by default), and all models
  share one total time budget (20 seconds). Once the budget is used up, no further model is started.

## Tech stack

| Part | Tools |
|---|---|
| App | Streamlit |
| GitHub data | PyGithub |
| Data | pandas |
| Charts | Plotly |
| AI workflow | LangGraph, LangChain |
| AI models | Gemini, with OpenRouter as the backup |
| Typed data and settings | Pydantic, pydantic-settings |
| Tests and CI | pytest, GitHub Actions |

## Project structure

```
repolens/
├── app.py                       Streamlit app
├── requirements.txt
├── pytest.ini
├── .env.example
├── .github/workflows/test.yml   runs the tests on every pull request
├── github_analyser/
│   ├── config.py                settings from .env (pydantic-settings)
│   ├── models.py                Profile and Repo dataclasses
│   ├── github_client.py         reads GitHub through PyGithub
│   ├── analytics.py             pandas: repos in, Facts out
│   ├── scoring.py               the 0-100 score
│   ├── charts.py                Plotly figures
│   ├── schemas.py               the shape of the AI review
│   ├── llm.py                   Gemini, with OpenRouter as the backup
│   ├── timing.py                hard deadline and shared time budget
│   ├── limits.py                daily budget for AI reviews
│   └── workflow.py              the LangGraph pipeline
└── tests/
```

The Python package is still called `github_analyser`. It is an internal name.

## Setup

You need Python 3.10 or newer. Run these in the project folder.

```bash
python -m venv venv
venv\Scripts\activate            # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # macOS/Linux: cp .env.example .env
```

Open `.env` and fill in your keys.

| Variable | Required | Default | What it is |
|---|---|---|---|
| `GITHUB_TOKEN` | yes | | GitHub personal access token. Read-only is enough. Without one GitHub allows only 60 requests per hour. |
| `GEMINI_API_KEY` | yes | | Google AI Studio key. This is the main AI model. |
| `OPENROUTER_API_KEY` | no | | Backup AI. Used only if Gemini fails. |
| `DAILY_REVIEW_LIMIT` | no | 50 | AI reviews per day, shared by all visitors |
| `REVIEW_DEADLINE_SECONDS` | no | 12 | The longest one AI model may take |
| `REVIEW_BUDGET_SECONDS` | no | 20 | The longest a whole review may take, across all models |

The OpenRouter models are listed in `github_analyser/llm.py` (`OPENROUTER_MODELS`). Each one must
support structured output. Check `openrouter.ai/models` and filter by "Structured outputs".

## Run

```bash
streamlit run app.py
```

## Tests

```bash
python -m pytest
```

The tests need no network and no API keys. GitHub Actions runs them on every pull request.

## Deploy

The app runs on Streamlit Community Cloud.

1. Push the code to GitHub.
2. On share.streamlit.io, create an app: your repo, branch `main`, main file `app.py`, Python 3.12.
3. In the app's Secrets, add your keys in TOML format:

```toml
GITHUB_TOKEN = "your-read-only-token"
GEMINI_API_KEY = "your-gemini-key"
# OPENROUTER_API_KEY = "your-openrouter-key"
```

The cache and the daily review counter live in the app's memory. They reset when the app restarts
or wakes up after a period without visitors.

## Scoring

Forks are left out of every category. Stars and followers are log-scaled, so going from 0 to 10
stars matters more than going from 100 to 110.

| Category | Points | How it is calculated |
|---|---|---|
| Profile quality | 15 | Bio (5), location or company (4), account age (6, full marks at one year) |
| Repository quality | 25 | Three equal parts: average stars per repo (full marks at 20), topics and license coverage, and recent pushes with few open issues (20 or fewer) |
| Documentation | 20 | Share of repos with a README (70%) and with a description (30%) |
| Project diversity | 15 | Languages used. Full marks at 3, one language earns a third. "Unknown" does not count. |
| Activity | 15 | Share of repos pushed to in the last 90 days (40%) and in the last year (60%) |
| Community | 10 | Followers (50%, full marks at 100) and stars plus forks on your own repos (50%, full marks at 200) |

## Privacy

RepoLens reads public GitHub data only. Nothing is written to a database or to disk. Results are
cached in the server's memory for up to an hour.

To write the review, the app sends this to the AI provider: the username, the bio (first 300
characters), the repository numbers, and the names, languages and descriptions (first 200
characters) of the five most-starred repos. The text from a profile is treated as data, and the
model is told never to follow instructions found in it. Insights about repo names that do not
exist are dropped.

## Known limitations

- The scoring weights are a starting point. They have not been tested against a large sample of real accounts.
- Only the 100 most recently pushed repos are read, and README checks cover the 30 most recent own repos. Each check is one extra API call. Repos that were not checked are left out of the README ratio. They are not counted as missing.
- Activity uses the last push date, not the "updated" date, because "updated" also changes when settings change.
- The daily review limit is a soft cap, because it resets when the app restarts.
- Free OpenRouter models have tight rate limits. They are used only when Gemini fails.
- Model names change often. They are constants at the top of `github_analyser/llm.py`.

## Ideas for later

- Compare two accounts side by side
- A LangGraph step that checks the AI's claims against the numbers and retries
- A daily limit stored outside the app, so a restart cannot reset it
- Calibrate the scoring weights on a sample of real profiles