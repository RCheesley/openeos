---
description: Host several organisations on one Empresadence server, and give each one its own web address.
---

# Host several organisations

One server can hold several organisations. Each has its own teams, Priorities, Blockers, Actions, Metrics Boards, Vision and Delivery Board and Org Chart. This suits a consultancy that runs its own company alongside each client.

## How people belong to organisations

- A person belongs to an organisation through a membership. The membership carries their role: Admin, Team Leader or Team Member.
- One person can be an Admin of one organisation and a Team Member of another.
- A person in more than one organisation sees **Switch Organisation** in the team menu of the navigation bar.
- Everything on screen belongs to the chosen organisation. That includes lists, search, and links to single records. If a link to a record in another organisation says "not found", switch organisation first.

See [How organisations, teams and roles fit together](../explanation/organisations-teams-and-roles.md).

## Create another organisation

Only a site administrator can create more organisations. There are two ways.

### In the browser

1. Sign in as a site administrator.
2. Select the team menu in the navigation bar, then **New organisation**. The address is `/org/setup/`.
3. Type the name and save.

You become the first Admin of the new organisation.

### From a script

Use the [`create_organization` command](#create-organization). It creates the organisation, its domain, an Admin and a first team in one step. It is safe to run again.

```bash
docker compose -f docker-compose.prod.yml exec -T web python manage.py create_organization \
  --name "Acme Ltd" --domain acme.example.com \
  --admin-username acme-admin --admin-email admin@acme.example.com
```

Leave `--admin-password` out. A random password is then generated and printed once.

(organisation-domains)=
## Give an organisation its own address

An organisation can own one or more hostnames, such as `acme.example.com`.

1. Point the hostname at your server in DNS.

2. Make sure `ALLOWED_HOSTS` covers the hostname. An entry that starts with a dot, such as `.example.com`, covers every subdomain. Restart the stack after you change it.

3. Sign in to the site administration at `/admin/` as a site administrator.

4. Under **Organization domains**, add the hostname and choose the organisation. You can also add it on the organisation's own page.

5. Optional: tick **Is primary** on one hostname for each organisation. Emails for that organisation then link to it and not to `SITE_URL`.

### What changes on an organisation's own address

- The request is tied to that organisation. The organisation switcher shows only that one, and any earlier choice is ignored.
- `/org/setup/` sends people back to the home page.
- A signed-in person who is not a member of that organisation sees a 403 page with a button to sign out. Site administrators are not blocked.
- The sign-in pages under `/accounts/`, the site administration under `/admin/` and the health check at `/healthz/` stay open to everyone.
- The sign-in page carries that organisation's name, logo and colours.

Addresses with no domain record keep the normal switcher.

## Manage memberships

There is no screen in the app to move a person between organisations or to change their role. A site administrator can do both in the site administration at `/admin/`, under **Memberships**.

## Move an organisation between servers

Export it on one server and import it on the other. See the [`export_organization`](#export-organization) and [`import_organization`](#import-organization) commands.
