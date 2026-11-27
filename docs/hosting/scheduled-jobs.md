---
description: Set up cron to send the daily emails and to delete old audit events. Empresadence has no background worker of its own.
---

# Schedule the daily jobs

Empresadence has no background worker. Two jobs need a scheduler on the server, such as cron.

## Before you start

- The production stack is running. See [Deploy to production](deploy-to-production.md).
- Email is set up with the `EMAIL_` variables. If `EMAIL_HOST` is empty, emails are printed to the container log and not sent.

## Daily emails

The [`send_daily_notifications` command](#send-daily-notifications) sends:

- a list of overdue Actions to each person who has any
- a reminder to each member of a team with a Weekly Meeting scheduled for that day

Run it once a day. Mornings work well.

1. Open the crontab of a user who can run Docker.

   ```bash
   crontab -e
   ```

2. Add this line. Change the path to where you cloned Empresadence.

   ```text
   0 7 * * * cd /path/to/empresadence && docker compose -f docker-compose.prod.yml exec -T web python manage.py send_daily_notifications
   ```

   This runs the job at 07:00 server time every day.

## Emails that need no schedule

These are sent at once, when the event happens:

- the invitation email for a new person
- the alert to the owner when a Priority changes to **Off Track**

## Audit log clean-up

The audit log grows for ever unless you prune it. The [`prune_audit_log` command](#prune-audit-log) deletes events older than a number of days. The default is 365.

To run it at 03:00 on the first day of each month, add this line to the same crontab:

```text
0 3 1 * * cd /path/to/empresadence && docker compose -f docker-compose.prod.yml exec -T web python manage.py prune_audit_log
```

Decide how long you must keep audit events before you schedule this.
