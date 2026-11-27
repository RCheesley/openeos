# Empresadence

An open-source, self-hosted platform for running your leadership team's operating rhythm — a weekly meeting, quarterly priorities, issue-solving, weekly action items, a metrics board, a long-term vision document, and a roles chart. Every module's vocabulary is configurable per organisation, so you're not locked into any one framework's words for them.

Built with Django, Bootstrap 5, PostgreSQL, and Docker. No JavaScript frameworks. No SaaS lock-in.

---

## Features

| Module | Description |
|--------|-------------|
| **Vision and Delivery Board** | Core Values, Core Focus, 10-Year Target, Marketing Strategy, 3-Year Picture, 1-Year Plan |
| **Org Chart** | Org-chart builder with seat owners, vacant seat tracking, and department grouping |
| **Priorities** | Quarterly priorities with on-track / off-track status, quarter labels, and dependency tracking |
| **Metrics Boards** | Weekly measurables with above/below/equal goal directions and colour-coded status cells |
| **Blockers** | PSR (Problem, Solve, Resolve) list with short-term / long-term types, cross-team delegation, and activity history |
| **Actions** | Weekly action items with escalation levels, due dates, and Priority/Blocker linking |
| **Audit log** | Logins, logouts, failed logins and administrative actions recorded per organisation; admins see their organisation's log, superusers see everything in the Django admin |
| **Data export** | Organisation admins can download everything that belongs to their organisation as one archive (JSON for importing, CSV for spreadsheets, logo and avatars); operators can export one or every organisation from the command line. Every export is written to the audit log; an archive can be loaded into another instance with `import_organization` |
| **Weekly Meeting** | Guided 90-minute meeting runner with timed segments, check-in entries, updates, PSR integration, ratings, and key messages |
| **Two-factor authentication** | Optional per user: an authenticator app (TOTP) plus ten single-use backup codes, set up from **My Profile**. Set `OTP_TOTP_ISSUER` to change the name shown in authenticator apps; a later change lets an organisation require it for its members |

---

## Documentation

The full documentation is in [`docs/`](docs/index.md).

| I want to | Read |
|---|---|
| Learn to use it | [Your first week](docs/tutorials/first-week.md) and the [how-to guides](docs/how-to/index.md) |
| Run it for my organisation | [Roles and what each can do](docs/reference/roles.md) |
| Install, deploy or upgrade it | [Hosting](docs/hosting/index.md) |
| Look up a setting or a command | [Configuration variables](docs/reference/configuration.md) and [Management commands](docs/reference/management-commands.md) |
| Work on it with an AI agent | [AGENTS.md](AGENTS.md) |
| Improve the docs | [docs/README.md](docs/README.md) |

---

## Quick Start (Development)

**Requirements:** Docker and Docker Compose v2.

```bash
git clone https://github.com/drikusb/empresadence.git
cd empresadence
cp .env.example .env
docker compose up
```

The app starts at **http://localhost:8000**. Sign in as `admin` / `adminpass` and you are taken to the page that creates your first organisation.

[Install for development](docs/hosting/install-for-development.md) has the full steps.

---

## Configuration

All configuration is driven by environment variables. Copy `.env.example` to `.env` and edit it.

[Configuration variables](docs/reference/configuration.md) lists every variable with its default.

---

## Production Deployment

```bash
cp .env.example .env
# Edit .env: set SECRET_KEY, ALLOWED_HOSTS, strong passwords, MEDIA_ACCEL_REDIRECT=True
docker compose -f docker-compose.prod.yml up -d
```

This starts PostgreSQL 15, Gunicorn and Nginx on port 80. `GET /healthz/` reports whether the app can reach its database.

| Topic | Page |
|---|---|
| Settings, start-up, HTTPS, uploaded files and privacy, running as a non-root user | [Deploy to production](docs/hosting/deploy-to-production.md) |
| Upgrades | [Upgrade](docs/hosting/upgrade.md) |
| Daily email notifications and audit log clean-up | [Schedule the daily jobs](docs/hosting/scheduled-jobs.md) |
| Multiple organisations, organisation domains and `create_organization` | [Host several organisations](docs/hosting/multiple-organisations.md) |

---

## Running Tests

```bash
# Inside the dev container
docker compose exec web python manage.py test apps

# With coverage report
docker compose exec web coverage run manage.py test apps
docker compose exec web coverage report
```

---

## Project Structure

```
.
├── apps/
│   ├── accounts/       # Organisations, Memberships, Teams, UserProfiles
│   ├── accountability/ # Org Chart nodes and roles
│   ├── audit/          # Audit log
│   ├── issues/         # Blockers with PSR workflow
│   ├── meetings/       # Weekly Meeting runner
│   ├── notifications/  # Email notifications and preferences
│   ├── rocks/          # Quarterly Priorities
│   ├── scorecards/     # Weekly Metrics Boards
│   ├── todos/          # Actions
│   └── vision/         # Vision and Delivery Board
├── docs/               # Documentation (Sphinx, MyST Markdown)
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── wsgi.py
├── nginx/
│   └── nginx.conf
├── static/             # Source static files (CSS, JS)
├── staticfiles/        # Collected static files (git-ignored)
├── templates/          # Django HTML templates
├── docker-compose.yml          # Development
├── docker-compose.prod.yml     # Production
├── Dockerfile
├── entrypoint.sh
└── requirements.txt
```

---

## Tech Stack

- **Python 3.15** / **Django 6.1**
- **PostgreSQL 15**
- **Bootstrap 5.3** + Bootstrap Icons (CDN)
- **Gunicorn** (production WSGI)
- **Whitenoise** (static file serving / compression)
- **Nginx** (production reverse proxy)
- **Docker** + **Docker Compose v2**

No Node.js. No Webpack. No JavaScript build step.

---

## Contributing

Pull requests are welcome. For significant changes, please open an issue first to discuss what you'd like to change.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes with tests
4. Ensure the test suite passes (`docker compose exec web python manage.py test apps`)
5. Open a pull request

---

## License

[MIT](LICENSE)
