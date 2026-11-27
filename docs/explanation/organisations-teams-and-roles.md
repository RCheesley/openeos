---
description: How organisations, teams, people and roles relate in Empresadence, and what decides which records you see.
---

# How organisations, teams and roles fit together

Three things decide what you see and what you can do: your organisation, your teams, and your role.

Your organisation may have renamed some words. This page uses the default names. See the [glossary](../reference/glossary.md).

## The short version

```text
Server
└── Organisation            for example, Harbour Lights
    ├── People              each has one role here: Admin, Team Leader or Team Member
    ├── Vision and Delivery Board, Org Chart     one of each for the whole organisation
    └── Teams               for example, Leadership and Operations
        └── Priorities, Actions, Blockers, Metrics Boards, Weekly Meetings
```

## Organisations

An organisation is one company or group. It is the wall around your data. A person never sees records from an organisation they do not belong to.

One server can hold several organisations. This suits a consultancy that runs its own company and each client in the same place. Each organisation has its own people, teams, look and vocabulary.

A person can belong to more than one organisation, with a different role in each. If you do, the team menu in the navigation bar also lists your organisations under **Switch Organisation**. Everything on screen belongs to the organisation you have chosen.

An organisation can also have its own web address. When you use that address, you always see that organisation, and you cannot switch to another.

## Teams

A team is a group of people inside an organisation. Most records belong to exactly one team: Priorities, Actions, Blockers, Metrics Boards and Weekly Meetings.

Two things belong to the whole organisation and not to a team: the Vision and Delivery Board and the Org Chart.

A person can be in several teams. The navigation bar always names one of them. That team is the one you are working in:

- Lists show that team's records.
- A new Priority, Action or Blocker is saved to that team.

The Dashboard, the Priorities page and the Metrics Boards page can also show **All teams**. For most people that means all the teams they belong to. For an Admin it means every team in the organisation.

Teams also decide what you can open. A record that belongs to a team can be opened by the people in that team and by Admins. Anyone else who follows a link to it sees a "not found" page.

Company-wide Priorities and company-wide Blockers are the exception. Everyone in the organisation can see them.

## Roles

Your role belongs to your membership of one organisation. It is not tied to a team.

- An **Admin** manages the organisation itself: people, teams, settings, vocabulary, export and the audit log.
- A **Team Member** works in their teams.
- A **Team Leader** can do the same things as a Team Member today. The role exists as a label.

Some rules depend on who you are to a record, not on your role:

- Only the owner of a Priority, or an Admin, can check in on it or change its status.
- Only people in the team that raised a Blocker, or an Admin, can change its status.

[Roles and what each can do](../reference/roles.md) has the full table.

## Why it works this way

Each team's day-to-day work stays with that team, and the things the whole business steers by are shared. So a team's own Priorities, Actions, Blockers, numbers and meetings are for its members and for Admins. Company-wide Priorities, company-wide Blockers and the Vision and Delivery Board are for everyone in the organisation.

The few Admin-only tasks are the ones that change the organisation for everyone, or that take data out of it.
