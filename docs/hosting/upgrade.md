---
description: Upgrade a production Empresadence to a newer version with three commands. Migrations run on start-up.
---

# Upgrade

## Before you start

- Back up the database and the uploaded files.
- Read the release notes or the commit log for anything that needs action.

## Upgrade the production stack

1. Get the new code.

   ```bash
   git pull
   ```

2. Rebuild the image.

   ```bash
   docker compose -f docker-compose.prod.yml build --no-cache
   ```

3. Restart the stack.

   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```

   When the `web` container starts, it runs the database migrations and collects the static files. You do not run them by hand.

4. Check that it is healthy.

   ```bash
   curl http://localhost/healthz/
   ```

   You see `{"status": "ok"}`.

## If something goes wrong

Read the log of the `web` container. A failed migration stops the container from starting and shows there.

```bash
docker compose -f docker-compose.prod.yml logs web
```
