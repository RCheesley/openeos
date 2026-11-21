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
| **Blockers** | PRS (Problem, Solve, Resolve) list with short-term / long-term types, cross-team delegation, and activity history |
| **Actions** | Weekly action items with escalation levels, due dates, and Priority/Blocker linking |
| **Audit log** | Logins, logouts, failed logins and administrative actions recorded per organisation; admins see their organisation's log, superusers see everything in the Django admin |
| **Data export** | Organisation admins can download everything that belongs to their organisation as one archive (JSON for importing, CSV for spreadsheets, logo and avatars); operators can export one or every organisation from the command line. Every export is written to the audit log; an archive can be loaded into another instance with `import_organization` |
| **Personal data** | Anyone can download a copy of their own data from their profile; operators can erase a person with `erase_user`, which anonymises them and keeps the organisation's history (see [Personal data](#personal-data)) |
| **Weekly Meeting** | Guided 90-minute meeting runner with timed segments, check-in entries, updates, PRS integration, ratings, and key messages |
| **Two-factor authentication** | Optional per user: an authenticator app (TOTP) plus ten single-use backup codes, set up from **My Profile**. Set `OTP_TOTP_ISSUER` to change the name shown in authenticator apps; a later change lets an organisation require it for its members |

---

## Quick Start (Development)

**Requirements:** Docker and Docker Compose v2.

```bash
git clone https://github.com/drikusb/empresadence.git
cd empresadence
cp .env.example .env
docker compose up
```

The app starts at **http://localhost:8000**.

On first boot the entrypoint script:
- Runs all database migrations
- Collects static files
- Creates a superuser (`admin` / `adminpass` by default)

Log in at `/admin/` to set up your organisation, or visit the dashboard at `/` to get started.

### Multiple organisations

One deployment can host several organisations, each with its own teams, Priorities, Blockers, Actions, Metrics Boards, Vision and Delivery Board and Org Chart. This suits a consultancy running their own company alongside each client.

- A user belongs to an organisation through a **membership**, which carries their role (admin, team leader or member) in that organisation. The same user can be an admin of one organisation and a member of another.
- Superusers create additional organisations from the navbar switcher (**New organisation**) or at `/org/setup/`. The creator becomes its first admin.
- Members of more than one organisation see an **organisation switcher** in the navbar above the team switcher. Everything on screen, including lists, search and links by id, is scoped to the active organisation, so switch first if a link to another organisation returns "not found".
- Memberships can also be managed under **Memberships** in the Django admin.

To onboard an organisation from a script or a deploy hook, use the `create_organization` management command. It creates the organisation, its domain, an admin user with an admin membership and a first team (default `Leadership`) in one step, and is safe to re-run: existing records are reused and only the options
you pass are updated. Leave `--admin-password` out and a random password is generated and printed once (a password on the command line is visible in process listings). `--display-name`, `--primary-color`, `--team` and `--slug` are optional.

```bash
python manage.py create_organization --name "Acme Ltd" --domain acme.example.com \
  --admin-username acme-admin --admin-email admin@acme.example.com
```

### Organisation domains

An organisation can own one or more hostnames (for example `acme.example.com`), set under **Organization domains** in the Django admin or inline on the organisation itself. A request on one of those hostnames is pinned to that organisation: the switcher collapses to it, the session choice is ignored, and `/org/setup/` redirects home. A logged-in user who is not a member of that organisation gets a 403 page with a log-out button (superusers are exempt, as are `/accounts/`, `/admin/` and `/healthz/`). Mark one hostname as primary and emails for that organisation will link to it instead of `SITE_URL`. Every hostname must also appear in `ALLOWED_HOSTS`; a leading-dot entry such as `.example.com` covers all of its subdomains. Hosts with no domain record keep the session-based switcher.

---

## Configuration

All configuration is driven by environment variables. Copy `.env.example` to `.env` and edit it:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(dev key)* | Django secret key — **must** be changed in production |
| `DEBUG` | `True` | Set to `False` in production |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated list of valid hostnames |
| `DB_NAME` | `epd_db` | PostgreSQL database name |
| `DB_USER` | `epd_user` | PostgreSQL username |
| `DB_PASSWORD` | `epd_password` | PostgreSQL password |
| `DJANGO_SUPERUSER_USERNAME` | `admin` | Admin username created on first run |
| `DJANGO_SUPERUSER_PASSWORD` | `adminpass` | Admin password created on first run |
| `SECURE_SSL_REDIRECT` | `False` | Set `True` when TLS terminates at Nginx |
| `SECURE_HSTS_SECONDS` | `0` | HSTS max-age in seconds (e.g. `31536000`) |
| `MEDIA_ACCEL_REDIRECT` | `False` | Set `True` behind the bundled Nginx so it sends avatar files after Django has checked the request |

---

## Production Deployment

### 1. Configure your environment

```bash
cp .env.example .env
# Edit .env — set SECRET_KEY, ALLOWED_HOSTS, strong DB_PASSWORD, MEDIA_ACCEL_REDIRECT=True, etc.
```

Generate a secret key:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 2. Start the production stack

The production compose file adds Nginx in front of Gunicorn and serves static files directly:

```bash
docker compose -f docker-compose.prod.yml up -d
```

This starts:
- **PostgreSQL 15** — database with persistent volume
- **Gunicorn** — 3-worker Django WSGI server on port 8000 (internal only)
- **Nginx** — reverse proxy on port 80, serves `/static/` and organisation logos under `/media/` directly

**Uploaded files and privacy.** Organisation logos are public: they appear on the login page and are not personal data. User avatars are personal data, so `/media/avatars/` is never served straight from disk. Django checks every request and only returns an avatar to its owner, a superuser, or a member of an organisation the owner also belongs to; anyone else gets a 404. With `MEDIA_ACCEL_REDIRECT=True` Nginx still delivers the bytes (via `X-Accel-Redirect`) once Django has approved the request, so the extra check costs no Gunicorn worker time for the file transfer itself. Without a proxy, leave it unset and Django streams the file.

`GET /healthz/` returns `{"status": "ok"}` (or HTTP 503 when the database is unreachable) and needs no login, so point container healthchecks and load balancer probes at it.

`GET /healthz/` returns `{"status": "ok"}` (or HTTP 503 when the database is unreachable) and needs no login, so point container healthchecks and load balancer probes at it.

### 3. (Optional) TLS with a reverse proxy or load balancer

Point your TLS-terminating proxy (Nginx, Caddy, Cloudflare Tunnel, etc.) at port 80 of the host. Then set in `.env`:

```
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
```

### 4. Upgrades

```bash
git pull
docker compose -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.prod.yml up -d
```

Migrations and `collectstatic` run automatically on startup via `entrypoint.sh`.

### 5. Daily email notifications

The overdue To-Do digest and same-day meeting reminders are sent by a management command,
not a background worker — schedule it to run once a day (mornings work well) with the
host's cron:

```
0 7 * * * cd /path/to/empresadence && docker compose -f docker-compose.prod.yml exec -T web python manage.py send_daily_notifications
```

Rock off-track alerts and user-invite emails are sent immediately and need no scheduling.
Configure SMTP via the `EMAIL_*` variables in `.env` (see `.env.example`) — without
`EMAIL_HOST` set, emails print to the container logs instead of sending, which is fine for
development.

---

### 6. Running as a non-root user

The production image (the `production` stage of the `Dockerfile`, which `docker-compose.prod.yml` builds) runs as an unprivileged user, uid 1000 (`app`), rather than root. The named `static_volume` and `media_volume` volumes pick up the right ownership automatically; if you swap them for bind-mounted host directories, those directories must be writable by uid 1000. The development stack in `docker-compose.yml` builds the `development` stage, which stays root because it bind-mounts your checkout over `/app` and has to write `staticfiles/` there whoever owns the clone.

## Personal data

Two tools help whoever runs an instance answer a person who asks for a copy of their data or for it to be erased. Neither needs database access.

**A copy of a person's data.** Every signed-in person can download their own from **My Profile → Your data** after entering their password again. For someone who cannot sign in, run it for them:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py export_personal_data <username or email> --out /tmp
```

The zip holds a README and JSON files: the account (username, name, email, sign-in dates), profile and avatar, whether two-factor sign-in is on, notification preferences, memberships, roles and teams, every record that names the person in the organisations they belong to (as owner, creator, author, participant, rater, the one who entered a figure or last edited a section), and the audit and admin-site log entries of what they did. For an organisation they have left it gives the number of records that still name them, not the content. It never contains the password hash, two-factor secrets, backup codes or sessions, and it leaves other people's names out. Each download is written to the audit log.

**Erasure.** Look first, then run it:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py erase_user <username or email> --dry-run
docker compose -f docker-compose.prod.yml exec web python manage.py erase_user <username or email>
```

`--dry-run` lists exactly what would change and writes nothing. Without it the command asks you to type the username (`--yes` skips the question for scripts). It refuses to erase the only admin of an organisation or a superuser unless you add `--allow-last-admin` or `--allow-superuser`; hand the organisation to another admin first where you can. It cannot be undone, and it is safe to run again on an account that is already erased.

What is removed: the name, email and username, the password (which also ends any outstanding invite or password-reset link), the avatar file, two-factor devices and backup codes, sign-in sessions, every membership and team membership, site-wide groups and permissions, and the notification preferences (all switched off). On audit events the person caused, the username, IP address and browser are removed; events that name them lose the name and email.

What is retained, and why:

- **The account row**, switched off and renamed `erased-<id>` with the display name "Former member". It cannot sign in. It stays because each meeting keeps one check-in and one rating per participant; those rows remain on this empty account so the meeting's history and average are unchanged. The date the account was created also stays.
- **The organisation's records.** Priorities, Actions and metrics the person owned, and anything they created, wrote or last edited, now show a single shared account called "Former member" (`former-member`, created the first time it is needed, switched off, a member of nothing). Reassign open work to a current member afterwards.
- **What the person wrote.** Notes, comments, check-ins and updates are the organisation's record and are kept word for word, without the author's name. If the text itself mentions the person, edit it by hand.
- **An audit event** (`user.erased`) for the instance and for each organisation the person belonged to, recording that an erasure happened and how many records changed, with no name or email.

**Backups are outside its reach.** Database dumps, media backups and organisation export archives made before the erasure still contain the person. Let them expire on your retention schedule, and if you ever restore one, run `erase_user` again for everyone erased since it was taken (keep that list somewhere other than the instance).

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
│   ├── issues/         # Blockers with PRS workflow
│   ├── meetings/       # Weekly Meeting runner
│   ├── rocks/          # Quarterly Priorities
│   ├── scorecards/     # Weekly Metrics Boards
│   ├── todos/          # Actions
│   └── vision/         # Vision and Delivery Board
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

- **Python 3.11+** / **Django 5.x**
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
