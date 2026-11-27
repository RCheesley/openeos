# AGENTS.md

Guidance for AI agents and other automated tools working in this repository.

## What this project is

Empresadence is an open source, self-hosted web app for running a team's operating rhythm: quarterly Priorities with Steps, weekly Actions, Blockers, Metrics Boards, Weekly Meetings, a Vision and Delivery Board and an Org Chart. It is a Django app with a PostgreSQL database, Bootstrap 5 templates and no JavaScript build step. One deployment can host several organisations.

## Where things are

| Path | What it holds |
|---|---|
| `apps/` | One Django app for each module. See the table in `CONTRIBUTING.md` |
| `apps/accounts/terminology.py` | The default vocabulary. Each organisation can rename it |
| `apps/accounts/scoping.py` | Helpers that keep every request inside the active organisation and team |
| `config/settings/` | `base.py`, `development.py`, `production.py` |
| `templates/` | All Django templates |
| `docs/` | The documentation: MyST Markdown, built with Sphinx |
| `docs/contributing/style-guide.md` | The writing rules for the docs |
| `docs/reference/` | Roles, glossary, configuration variables, management commands |

The built documentation site has `llms.txt` and `llms-full.txt` at its root.

## Words

- User-facing text uses the default vocabulary through the terminology helpers: `{{ terms.rock }}` in templates, `get_terms(request)` or `terms_for(org)` in Python. Never hardcode these words in templates or messages.
- Code identifiers keep their older names (`Rock`, `ToDo`, `Issue`, `Scorecard`). Do not rename them, and do not show them to users.
- Do not reintroduce the trademarked words listed in `TRADEMARK-REMEDIATION.md`, in the interface or in the docs.
- User-facing text uses British spelling, such as "organisation".

## Run the app

```bash
cp .env.example .env
docker compose up
```

The app is at `http://localhost:8000`.

## Run the tests

```bash
docker compose exec web python manage.py test apps
docker compose exec web python manage.py makemigrations --check --dry-run
```

CI also needs model-layer coverage of at least 60%. Add tests with new features.

## Build and lint the docs

Run from the top of the repository.

```bash
# Build. Warnings are errors.
docker run --rm -v "$PWD":/work -w /work python:3.15-slim sh -c \
  "pip install -q -r docs/requirements.txt && sphinx-build -W --keep-going -b html docs docs/_build/html"

# Lint the writing. Errors must be fixed.
docker run --rm -v "$PWD":/work -w /work jdkato/vale:v3.29.0 sync
docker run --rm -v "$PWD":/work -w /work jdkato/vale:v3.29.0 --glob='!**/_build/**' docs

# Check images and the screenshot manifest.
docker run --rm -v "$PWD":/work -w /work python:3.15-slim python docs/_tools/check_images.py
```

`docs/README.md` has more, including how to regenerate the screenshots.

## Conventions

These come from `CONTRIBUTING.md`. Read it before you change code.

- Python follows PEP 8, with lines under 100 characters.
- Views are class based, with `LoginRequiredMixin` on everything. No raw SQL.
- Templates use Bootstrap 5 only, with minimal plain JavaScript.
- Comments say why, not what. No print statements.
- Commit migrations with the model changes that need them.
- Every record reachable by primary key must be limited to the active organisation. Use `OrgScopedMixin` or `get_org_object_or_404()` from `apps/accounts/scoping.py`, and add the new address to `apps/accounts/tests/test_isolation.py`.
- Forms take a `team=` argument so their choices are limited to the active team. Do not make `team` a form field.
- Branch from `main` as `feature/<name>`, `fix/<name>` or `chore/<name>`. Keep each pull request to one feature or fix.
- Commit messages use the imperative mood, with a subject line under 72 characters.

## When you change behaviour

Update the docs in the same pull request. Check every statement in the docs against the code or the running app. If a change alters the interface, regenerate the screenshots.
