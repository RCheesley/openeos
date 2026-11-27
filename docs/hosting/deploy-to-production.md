---
description: Deploy Empresadence with the production Docker Compose stack. Settings, start-up, the health check, HTTPS, uploaded files and the user the container runs as.
---

# Deploy to production

The production stack runs three containers: PostgreSQL 15, the app under Gunicorn, and Nginx in front.

## Before you start

You need:

- a server with Docker and Docker Compose v2
- a domain name that points at the server
- a way to provide HTTPS in front of port 80, such as a load balancer, Caddy or another reverse proxy
- an SMTP account, if you want Empresadence to send email

## Configure your environment

1. Get the code and create the settings file.

   ```bash
   git clone https://github.com/drikusb/empresadence.git
   cd empresadence
   cp .env.example .env
   ```

2. Generate a secret key.

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(50))"
   ```

3. Edit `.env`. Set at least these:

   | Variable | Set it to |
   |---|---|
   | `SECRET_KEY` | The key you generated |
   | `ALLOWED_HOSTS` | Your domain name. Separate several with commas |
   | `DB_PASSWORD` and `POSTGRES_PASSWORD` | One strong password, the same in both |
   | `DJANGO_SUPERUSER_PASSWORD` | A strong password for the first site administrator |
   | `MEDIA_ACCEL_REDIRECT` | `True` |
   | `SITE_URL` | The public address, such as `https://app.example.com`, with no slash at the end |
   | `EMAIL_HOST` and the other `EMAIL_` values | Your SMTP details |

   :::{warning}
   `.env.example` sets the first site administrator to `admin` with the password `adminpass`. The container creates that account on first start. Change `DJANGO_SUPERUSER_PASSWORD` before you start the stack.
   :::

   [Configuration variables](../reference/configuration.md) lists every setting.

## Start the stack

1. Build and start.

   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```

   This starts:

   | Service | What it does |
   |---|---|
   | `db` | PostgreSQL 15, with its data in a named volume |
   | `web` | Gunicorn with 3 workers on port 8000, reachable only from inside the stack |
   | `nginx` | Listens on port 80, passes requests to `web`, and serves `/static/` and organisation logos itself |

   Migrations and static file collection run each time the `web` container starts.

2. Check that it is healthy.

   ```bash
   curl http://localhost/healthz/
   ```

   You see `{"status": "ok"}`.

(health-check)=
## Health check

`GET /healthz/` needs no sign-in. It returns `{"status": "ok"}`, or HTTP 503 when the database cannot be reached. Point container health checks and load balancer probes at it.

## Add HTTPS

The bundled Nginx listens on plain HTTP on port 80. Put something that handles TLS in front of it and send its traffic to port 80 on the server.

Then set these in `.env` and restart the stack:

```text
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
```

The app decides whether a request used HTTPS from the `X-Forwarded-Proto` header.

:::{caution}
Check this before you rely on it. The bundled `nginx/nginx.conf` sets `X-Forwarded-Proto` itself, from its own plain HTTP connection. After you turn on `SECURE_SSL_REDIRECT`, load the site and sign in. If the browser reports too many redirects, edit `nginx/nginx.conf` so that it passes on the header your proxy sends.
:::

## Create your first organisation

Sign in as the site administrator and follow [Sign in and create your organisation](install-for-development.md#sign-in-and-create-your-organisation).

To create an organisation from a script instead, use the [`create_organization` command](#create-organization).

## Uploaded files and privacy

- **Organisation logos are public.** They can appear on the sign-in page. Nginx serves them straight from disk under `/media/`.
- **Profile pictures are personal data.** They are never served straight from disk. Django checks every request under `/media/avatars/`. It returns a picture only to its owner, to a site administrator, or to someone who shares an organisation with the owner. Anyone else gets a 404.

With `MEDIA_ACCEL_REDIRECT=True`, Django makes the check and Nginx then sends the file. Without a proxy, leave it unset and Django sends the file itself.

## The user the container runs as

The production image runs as an unprivileged user called `app`, with user ID 1000, not as root.

The named volumes `static_volume` and `media_volume` get the right ownership on their own. If you replace them with folders on the host, make those folders writable by user ID 1000.

The development stack is different. It mounts your checkout over `/app` and runs as root, so it works whoever owns the files.

## What happens next

- [Schedule the daily jobs](scheduled-jobs.md), or no daily emails are sent.
- Plan your backups. The database is in the `postgres_data` volume and uploaded files are in `media_volume`.
- When a new version comes out, see [Upgrade](upgrade.md).
