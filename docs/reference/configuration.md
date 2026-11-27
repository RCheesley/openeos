---
description: Every environment variable Empresadence reads, with its default and what it does.
---

# Configuration variables

Empresadence reads its settings from environment variables. Copy `.env.example` to `.env` and edit it.

"Default" is the value used when the variable is not set.

## Required for production

| Variable | Default | What it does |
|---|---|---|
| `SECRET_KEY` | A development key | Django's secret key. Set a long random value in production |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Hostnames the app answers on, separated by commas. An entry that starts with a dot, such as `.example.com`, covers every subdomain |
| `DB_PASSWORD` | `epd_password` | PostgreSQL password. Change it in production |

## Database

| Variable | Default | What it does |
|---|---|---|
| `DB_NAME` | `epd_db` | PostgreSQL database name |
| `DB_USER` | `epd_user` | PostgreSQL username |
| `DB_PASSWORD` | `epd_password` | PostgreSQL password |
| `DB_HOST` | `localhost` | Hostname of the PostgreSQL server. `.env.example` sets it to `db`, the name of the service in the compose files |
| `DB_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | None | Read by the PostgreSQL container in `docker-compose.prod.yml` to create the database on first start. Keep them the same as the `DB_` values |

## First site administrator

| Variable | Default | What it does |
|---|---|---|
| `DJANGO_SUPERUSER_USERNAME` | None | If set, `entrypoint.sh` creates a site administrator with this username when the container starts, unless one with that username exists |
| `DJANGO_SUPERUSER_EMAIL` | None | Email address for that account |
| `DJANGO_SUPERUSER_PASSWORD` | None | Password for that account |

`.env.example` and `docker-compose.yml` set these to `admin`, `admin@example.com` and `adminpass`. Change the password before you deploy.

## Web and security

| Variable | Default | What it does |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | See note | Which settings file to load: `config.settings.development` or `config.settings.production`. The compose files set it |
| `DEBUG` | `True` | Read by the base settings only. Both shipped settings files set debug mode themselves, so this variable has no effect with them |
| `SECURE_SSL_REDIRECT` | `False` | Production only. Set `True` to redirect HTTP to HTTPS when TLS ends at a proxy in front of the app |
| `SECURE_HSTS_SECONDS` | `0` | Production only. How long browsers should insist on HTTPS, in seconds. For example, `31536000` is one year |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `False` | Production only. Apply the HTTPS rule to subdomains too |
| `SECURE_HSTS_PRELOAD` | `False` | Production only. Allow the site to be added to browsers' built-in HTTPS lists |
| `MEDIA_ACCEL_REDIRECT` | `False` | Set `True` behind the bundled Nginx, so Nginx sends profile pictures after Django has checked the request |
| `DJANGO_LOG_LEVEL` | `WARNING` | Production only. Log level for Django's own messages |
| `EXTRA_INSTALLED_APPS` | Empty | Extra Django apps to load, separated by commas. They must be installed in the image |

`manage.py` uses `config.settings.development` unless `DJANGO_SETTINGS_MODULE` is set. The web server entry point, `config/wsgi.py`, uses `config.settings.production`.

## Email

| Variable | Default | What it does |
|---|---|---|
| `EMAIL_HOST` | Empty | SMTP server. If empty, emails are printed to the container log and not sent |
| `EMAIL_PORT` | `587` | SMTP port |
| `EMAIL_HOST_USER` | Empty | SMTP username |
| `EMAIL_HOST_PASSWORD` | Empty | SMTP password or API key |
| `EMAIL_USE_TLS` | `True` | Use TLS when talking to the SMTP server |
| `DEFAULT_FROM_EMAIL` | `Empresadence <noreply@example.com>` | Sender name and address |
| `SITE_URL` | `http://localhost:8000` | Address used to build links in emails. No slash at the end. An organisation with its own primary domain uses that domain |

## Names and limits

| Variable | Default | What it does |
|---|---|---|
| `BRAND_NAME` | `Empresadence` | Name shown in the navigation bar, page titles and emails when no organisation's own name applies |
| `OTP_TOTP_ISSUER` | `Empresadence` | Name shown in authenticator apps for two-step sign-in |
| `EXPORT_MAX_BYTES` | `524288000` | Largest archive the browser export builds, in bytes. The default is 500 MB. The `export_organization` command has no limit |
