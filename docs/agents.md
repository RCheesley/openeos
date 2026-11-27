---
description: Entry points for AI agents and other programs. Where to find llms.txt, the Markdown source of every page, the reference tables and the project conventions.
---

# If you are an AI agent

This page is for a program reading these docs, or for a person setting one up.

## Machine-readable entry points

| What | Where | Use it for |
|---|---|---|
| Index of every page | `llms.txt` at the root of this site | Finding the right page. Each entry has a one-line description |
| Every page in one file | `llms-full.txt` at the root of this site | Loading the whole documentation at once |
| Markdown source of one page | The page address with `.md` in place of `.html` | Reading a single page without HTML |
| Instructions for work in the repository | `AGENTS.md` at the top of the repository | Building, testing and the project conventions |

Every page has a `description` in its front matter. It is also in the page's HTML as `<meta name="description">`.

## Where the facts are

| Question | Page |
|---|---|
| Who is allowed to do what? | [Roles and what each can do](reference/roles.md) |
| What does this word mean, and what is it called in the code? | [Glossary](reference/glossary.md) |
| What does this setting do? | [Configuration variables](reference/configuration.md) |
| How is an organisation created, exported or imported from a script? | [Management commands](reference/management-commands.md) |
| How do records relate to each other? | [How organisations, teams and roles fit together](explanation/organisations-teams-and-roles.md) and [How the pieces of the weekly rhythm connect](explanation/weekly-rhythm.md) |

## Things to know before you act for a person

- **Words on screen can differ from these docs.** Each organisation can rename the vocabulary. The docs use the defaults. The glossary gives the key for each word.
- **Words in the code differ from words on screen.** Addresses and models keep older names. For example, Priorities are at `/rocks/`, Actions at `/todos/`, Blockers at `/issues/` and Metrics Boards at `/scorecards/`. Do not show those names to a person.
- **Everything happens inside one organisation and one team.** A new Priority, Action or Blocker is saved to the team named in the navigation bar, whatever the form shows.
- **How-to guides give exact labels and addresses.** Labels are in bold and match the screen. Addresses are in code formatting.
- **Nothing is only in a picture.** Every screenshot has alt text, and the steps say the same thing in words.

## Addresses of the main pages

| Page | Address |
|---|---|
| Sign in | `/accounts/login/` |
| Dashboard | `/` |
| Priorities | `/rocks/` |
| New Priority | `/rocks/new/` |
| Blockers | `/issues/` |
| New Blocker | `/issues/new/` |
| Actions | `/todos/` |
| New Action | `/todos/new/` |
| Metrics Boards | `/scorecards/` |
| Weekly Meetings | `/meetings/` |
| Schedule a Weekly Meeting | `/meetings/create/` |
| Vision and Delivery Board | `/vision/` |
| Org Chart | `/accountability/` |
| Your profile | `/profile/` |
| Organisation | `/org/` |
| Organisation settings | `/org/settings/` |
| Terminology | `/org/settings/terminology/` |
| Export data | `/org/export/` |
| Audit log | `/org/audit/` |
| Teams | `/teams/` |
| Users | `/users/` |
| Invite a user | `/users/invite/` |
| Search | `/search/?q=` followed by your words |
| Health check | `/healthz/` |

There is no public API in this version. A program works through the same pages a person uses, or through the [management commands](reference/management-commands.md) on the server.

## If you change these docs

Follow the [style guide](contributing/style-guide.md) and [Add a page](contributing/add-a-page.md). Check every statement about behaviour against the code. If you cannot check it, leave it out.
