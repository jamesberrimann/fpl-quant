# FPL Decision-Support Tool

A personal project I built to make better Fantasy Premier League decisions. It ingests live gameweek data from the public FPL API and uses a linear-programming optimizer, position-aware scoring, and real fixture/reliability signals to help with squad building, transfers, lineup selection, and captaincy.

I built this primarily as a portfolio project while studying CS and Business Computing at UCT. The goal was to build something genuinely useful, not just a tutorial rehash, so I tried to solve real FPL edge cases: fixture timing, regression risk, captain ceiling vs. reliability, and live vs. stale score data.

---

## Features

**Squad optimizer**
Builds the best possible 15-player squad from scratch under a given budget using integer linear programming (PuLP with CBC solver). Respects position limits, the 100m budget constraint, and the max-3-players-per-club rule. The scoring model blends recent form, fixture difficulty (split by attack/defense using real goals data, not FPL's built-in strength ratings), expected goals, expected goals conceded, and defensive contribution. Returns a clear 422 error if no legal squad exists for the given budget rather than silently returning an illegal result.

**Squad rating**
Takes your actual FPL entry ID and scores your current squad against the same model. Returns per-player scores with position percentiles and flags players at regression risk (GKP/DEF who are riding strong results on weak underlying xGC numbers).

**Transfer suggestions**
Generates ranked, deduplicated transfer suggestions with a shared depleting budget across multiple recommendations. Enforces club limits, labels free transfers vs. hits, and adds a fixture-timing caution when an incoming player's immediate next fixture is notably harder than their medium-term schedule.

**Lineup and captaincy**
Selects the best legal starting XI and formation from your squad and orders the bench. Captain and vice-captain are picked using a separate ceiling-weighted model tuned for single-gameweek explosiveness rather than season-long reliability. Reports honestly when a recommendation required breaking a statistical tie.

**Live scores and events**
Returns current gameweek scores and per-player events (goals, assists, bonus, defensive contribution). Correctly distinguishes genuinely live data from a player or team's last-played match when the current fixture has not kicked off yet.

**Fixture planning view**
A 6-gameweek heatmap showing upcoming fixture difficulty across your squad, useful for planning chip timing and rotation.

---

## Stack

| Layer | Tech |
|---|---|
| API | FastAPI (async), API-key authenticated via `X-API-Key` header |
| Database | PostgreSQL via SQLAlchemy (async) + Alembic migrations |
| Optimizer | PuLP with CBC solver (integer linear programming) |
| Scheduling | APScheduler, background ingestion every 3 hours |
| Data source | Public FPL API at `fantasy.premierleague.com/api` |
| Frontend | Plain HTML/CSS/vanilla JS, no build step, served via FastAPI StaticFiles |
| CI | GitHub Actions, runs tests and `pip-audit` on every push |

---

## Local setup

Prerequisites: Python 3.12, Docker (for Postgres).

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install

cp .env.example .env       # set DATABASE_URL and API_KEY
docker compose up -d       # starts Postgres on port 5432
alembic upgrade head       # runs migrations
uvicorn app.main:app --reload
```

Once running:
- Frontend: `http://localhost:8000/`
- API: `http://localhost:8000/api/v1/`
- Interactive docs: `http://localhost:8000/docs`

All API routes (except `/health`) require the `X-API-Key` header set to the value in your `.env`.

---

## Running tests

```bash
pytest tests/ -v
pytest tests/ --cov=app --cov-report=term-missing
```

Test coverage is around 95%+ on the service layer.

---

## Project structure

```
app/
├── core/          config (pydantic-settings), DB session, auth, scheduler
├── models/        SQLAlchemy ORM models (Player, Team, Fixture, GameweekStats)
├── schemas/       Pydantic request/response models
├── ingestion/     FPL API client with retry logic and data mappers
├── services/      all business logic (scoring, optimizer, lineup, captaincy,
│                  transfers, scores, fixtures, squad builder, squad rating)
└── api/v1/        versioned route handlers, one file per feature

frontend/          standalone HTML pages: index, optimize, rate-squad,
                   transfers, lineup, fixture-plan

tests/
├── api/           route-level integration tests
├── ingestion/     FPL client and mapper unit tests
└── services/      service-layer unit tests (~95% coverage)

alembic/           database migrations
```

---

## Design decisions worth knowing

**Fixture ease is computed from real results, not FPL's strength ratings.**
FPL publishes `strength_attack_home/away` etc. on each team, but these have been empty or unreliable this season. Instead, I compute fixture ease from actual goals scored and conceded from the `Fixture` table, split by attack/defense: attackers get eased against opponents who concede a lot, defenders against opponents who score a lot.

**Captaincy uses a different model from general scoring.**
The general scoring model weights reliability (minutes played, consistency) heavily because you want it for the full season. Captaincy is a single-gameweek decision where ceiling matters more, so the captain model up-weights form and expected goals and down-weights the reliability penalties.

**The optimizer raises an error on infeasible budgets rather than returning a partial result.**
Some LP solvers return whatever partial solution they found when a problem is infeasible. I check the solver status explicitly and raise `InfeasibleBudgetError` (which surfaces as a 422) so the caller knows nothing legal was found.

---

## Known limitations

- **FPL id stability:** Team and player ids use FPL's own element/team ids. These are not guaranteed stable across a season boundary (promoted clubs can shift which id maps to which team). Verify ids at the start of a new season before trusting the upsert logic.
- **No calibrated points model:** The scoring model is a normalized composite for ranking, not a predicted-points figure. Transfer suggestions show a score improvement, not an expected points gain.
- **Bench ordering is approximate:** The bench is ordered by score alone. It does not simulate whether a substitution would still leave a legal formation, which is how FPL's actual auto-sub logic works. It is correct in most cases but not guaranteed for every formation edge case.
- **Multi-transfer edge cases:** Transfer interactions beyond shared budget and club-limit checks have not been exhaustively tested for complex combinations like two simultaneous transfers into the same position.
