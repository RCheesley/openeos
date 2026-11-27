---
description: How to install Empresadence for development, deploy it to production, upgrade it, schedule its daily jobs and host several organisations.
---

# Hosting

These pages are for the person who runs the server. You need to be comfortable with a command line and Docker.

Empresadence is a Django app with a PostgreSQL database. It ships with Docker Compose files for development and for production. There is no JavaScript build step.

- [Install for development](install-for-development.md): run it on your own computer in a few minutes
- [Deploy to production](deploy-to-production.md): run it for real, behind Nginx
- [Upgrade](upgrade.md): move to a newer version
- [Schedule the daily jobs](scheduled-jobs.md): daily emails and audit log clean-up
- [Host several organisations](multiple-organisations.md): one server, many organisations, each on its own address

For every setting, see [Configuration variables](../reference/configuration.md). For commands, see [Management commands](../reference/management-commands.md).

```{toctree}
:hidden:

install-for-development
deploy-to-production
upgrade
scheduled-jobs
multiple-organisations
```
