---
description: The default words Empresadence uses, what each means, and the key used to rename it. Every organisation can rename these words.
---

# Glossary

Every organisation can rename the words in the first table. An Admin does this on the **Terminology** page. See [Rename the vocabulary](../how-to/rename-the-vocabulary.md).

These docs always use the default words, with a capital letter.

(default-vocabulary)=
## Words an organisation can rename

The defaults come from `apps/accounts/terminology.py`.

| Default word | Plural | Meaning | Key |
|---|---|---|---|
| Priority | Priorities | One important result a team has agreed to deliver this quarter. It has one owner | `rock` |
| Step | Steps | A smaller stage on the way to finishing a Priority | `milestone` |
| Action | Actions | A small task for one person to finish within about a week | `todo` |
| Blocker | Blockers | A problem, obstacle or open question that is slowing a team down | `issue` |
| Metrics Board | Metrics Boards | A table of numbers a team checks every week, each with a goal | `scorecard` |
| Weekly Meeting | Weekly Meetings | The meeting a team holds every week, run to a fixed agenda | `meeting` |
| Vision and Delivery Board | Vision and Delivery Boards | The organisation's long-term vision and plan, on one page | `vto` |
| Org Chart | Org Charts | A chart of the jobs in the organisation and who holds each | `accountability_chart` |
| Role | Roles | One box on the Org Chart: a job, held by one person or vacant | `seat` |
| Value | Values | A principle the organisation works by, listed on the Vision and Delivery Board | `core_value` |
| Update | Updates | One line of good news or concern shared in a Weekly Meeting | `headline` |
| Check-in | Check-ins | The opening part of a Weekly Meeting, where each person shares a personal best and a business best | `segue` |
| PSR | PSR | Problem, Solve, Resolve. The part of a Weekly Meeting where the team works through Blockers | `ids` |
| Key Message | Key Messages | Something the rest of the organisation needs to hear after a Weekly Meeting | `cascading_message` |

The key is the name the code uses. You need it only if you set words from a script.

## Words that stay the same

| Word | Meaning |
|---|---|
| Organisation | One company or group using Empresadence. One server can hold several |
| Team | A group of people inside an organisation. Most records belong to one team |
| Admin, Team Leader, Team Member | The three roles a person can have in an organisation. See [Roles and what each can do](roles.md) |
| Dashboard | The first page after you sign in. It counts what is open across your teams |
| Owner | The one person who answers for a Priority, an Action or a metric |
| Metric | One row on a Metrics Board: a number, its goal, and its owner |
| Check-in on a Priority | A weekly note from the owner of a Priority saying whether it is on track. This is different from the Check-in at the start of a Weekly Meeting |
| On Track, Off Track, Complete, Dropped | The four statuses of a Priority |
| Short-term, Long-term | The two types of Blocker |
| Company-wide | A Priority or long-term Blocker that an Admin has marked to show on the Vision and Delivery Board |
| Quarter | Three months. Q1 is January to March, Q2 is April to June, Q3 is July to September, Q4 is October to December |

## A sentence for other pages

When a page uses these words, it reminds the reader once, near the top:

> Your organisation may have renamed some words. This page uses the default names. See the glossary.
