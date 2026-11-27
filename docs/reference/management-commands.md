---
description: The five management commands Empresadence adds, with their options and examples for the production compose stack.
---

# Management commands

Empresadence adds five commands to Django's `manage.py`. Run them inside the web container.

With the production stack, start each command with:

```bash
docker compose -f docker-compose.prod.yml exec -T web python manage.py
```

With the development stack, use `docker compose exec web python manage.py`.

| Command | What it does |
|---|---|
| [`create_organization`](#create-organization) | Creates an organisation, its domain, its first Admin and its first team |
| [`export_organization`](#export-organization) | Writes one or every organisation to a zip archive |
| [`import_organization`](#import-organization) | Loads an archive as a new organisation |
| [`send_daily_notifications`](#send-daily-notifications) | Sends the daily emails |
| [`prune_audit_log`](#prune-audit-log) | Deletes old audit events |

(create-organization)=
## `create_organization`

Creates an organisation, a domain for it, an Admin account and a first team in one step. It is safe to run again: existing records are reused, and only the options you pass are updated.

| Option | Required | What it does |
|---|---|---|
| `--name` | Yes | Organisation name |
| `--domain` | Yes | Hostname the organisation answers on, such as `acme.example.com`. No scheme, port or path |
| `--admin-username` | Yes | Username of the first Admin |
| `--admin-email` | Yes | Email address of the first Admin |
| `--admin-password` | No | Password for the Admin. If you leave it out, a random password is generated and printed once. A password on the command line is visible to other users of the server |
| `--display-name` | No | Name shown in the navigation bar and emails |
| `--primary-color` | No | Main colour as a hex value, such as `#0d6efd` |
| `--team` | No | Name of the first team. The default is `Leadership` |
| `--slug` | No | Short name used in addresses and file names. The default is made from the organisation name |

```bash
python manage.py create_organization --name "Acme Ltd" --domain acme.example.com \
  --admin-username acme-admin --admin-email admin@acme.example.com
```

The hostname must also be covered by `ALLOWED_HOSTS`. See [Configuration variables](configuration.md).

(export-organization)=
## `export_organization`

Writes an organisation to a zip archive. Each export is written to the audit log.

| Argument or option | What it does |
|---|---|
| `slug` | Short name of the organisation to export. Give this or `--all`, not both |
| `--all` | Export every organisation, and write `instance-manifest.json` listing the archives |
| `--out DIR` | Folder to write into. The default is the current folder |

```bash
python manage.py export_organization acme-ltd --out /tmp/exports
```

The archive has the same contents as the browser export. See [Export your organisation's data](../how-to/export-your-data.md).

(import-organization)=
## `import_organization`

Loads an archive written by `export_organization` or by the browser export. The records arrive as a new organisation.
People are matched by username: an existing account is reused, and a missing one is created without a password, so its owner sets one with **Forgot password?**.

| Argument or option | What it does |
|---|---|
| `archive` | Path to the zip archive |
| `--slug` | Short name for the imported organisation. The default is the one in the archive |
| `--name` | Name for the imported organisation. The default is the one in the archive |
| `--dry-run` | Load everything, report what would be created, then undo it. Nothing is changed |

```bash
python manage.py import_organization /tmp/exports/archive.zip --dry-run
```

(send-daily-notifications)=
## `send_daily_notifications`

Sends two kinds of email:

- to each person with overdue Actions, one list of them for each organisation
- to each member of a team that has a Weekly Meeting scheduled for today

It has no options. Run it once a day from a scheduler. See [Schedule the daily jobs](../hosting/scheduled-jobs.md).

People can turn each kind of email off for themselves.

(prune-audit-log)=
## `prune_audit_log`

Deletes audit events older than a number of days.

| Option | What it does |
|---|---|
| `--days` | Delete events older than this many days. The default is `365` |

```bash
python manage.py prune_audit_log --days 730
```
