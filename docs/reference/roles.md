---
description: The three roles in an organisation (Admin, Team Leader, Team Member), the site administrator, and a table of what each can do.
---

# Roles and what each can do

Your organisation may have renamed some words. This page uses the default names. See the [glossary](glossary.md).

## The three roles in an organisation

A person has one role in each organisation they belong to. The role is set when they are invited.

| Role | Summary |
|---|---|
| **Admin** | Manages the organisation: people, teams, settings, words, export and the audit log. Sees every team |
| **Team Leader** | The same abilities as a Team Member. The role is a label only |
| **Team Member** | Works in the teams they belong to |

One more kind of account sits outside organisations:

| Account | Summary |
|---|---|
| Site administrator | A superuser account on the server. It counts as an Admin of every organisation, and it can create more organisations |

(what-each-role-can-do)=
## What each role can do

| Task | Admin | Team Leader | Team Member |
|---|---|---|---|
| See the Dashboard and the lists for teams they belong to | Yes | Yes | Yes |
| See lists for every team in the organisation, using **All teams** | Yes | No | No |
| Open a record that belongs to a team they are in | Yes | Yes | Yes |
| Open a record that belongs to a team they are not in | Yes | No | No |
| See company-wide Priorities and company-wide Blockers | Yes | Yes | Yes |
| Create a Priority, Action or Blocker in a team they belong to | Yes | Yes | Yes |
| Change the status of a Priority, or check in on it | Yes | Only if they own it | Only if they own it |
| See the controls to add, edit or remove Steps on a Priority page | Yes | Only if they own it | Only if they own it |
| Mark a Priority as company-wide | Yes | No | No |
| Change the status of a Blocker, or hand it to another team | Yes | Only if they are in the team that raised it | Only if they are in the team that raised it |
| Mark a long-term Blocker as company-wide | Yes | No | No |
| Comment on a Blocker | Yes | Yes | Yes |
| Create a Metrics Board, add metrics and enter numbers | Yes | Yes | Yes |
| Schedule, start, run and complete a Weekly Meeting | Yes | Yes | Yes |
| Edit the Vision and Delivery Board and the Org Chart | Yes | Yes | Yes |
| See the **Users** page and invite people | Yes | No | No |
| Create a team, edit a team, and change who is in it | Yes | No | No |
| Change **Organisation settings** (name, logo, colours) | Yes | No | No |
| Change **Terminology** | Yes | No | No |
| Export the organisation's data | Yes | No | No |
| Read the audit log | Yes | No | No |
| Turn on two-step sign-in for their own account | Yes | Yes | Yes |

## How the rules work

- **Admin only** tasks check the role. A Team Leader or Team Member who opens one of those pages sees an error page.
- **Owner** tasks check who owns the Priority. The owner is the person named in **Owner**.
- For other tasks, Empresadence checks that you are signed in, and that you are in the team the record belongs to or are an Admin. Anyone else sees a "not found" page.
- Company-wide Priorities and company-wide Blockers can be seen by everyone in the organisation. Seeing one does not let you change it.
- A person never sees records from an organisation they do not belong to.

## Things that are not roles

- **Team membership** decides which team names you can pick in the navigation bar, which lists you see and which records you can open. It is separate from your role. An Admin also needs to be in a team to create records for it.
- **Owner** is a field on a Priority, an Action or a metric. It is not a role.
- **Role** in the glossary is a different thing: a box on the Org Chart.

## Change what a person can do

There is no button in the app to change a person's role after they are invited.
A site administrator can change it in the site administration at `/admin/`, under **Memberships**.

## Site administration

The **Admin** item in the user menu opens Django's site administration at `/admin/`. Only accounts marked as staff on the server can sign in there. Being an Admin of an organisation does not give access to it.
