---
description: Run Empresadence on your own computer with Docker Compose, sign in as the first site administrator and create your first organisation and team.
---

# Install for development

This gets Empresadence running on your own computer. Use it to try the tool or to work on the code. Do not use it for real data.

## Before you start

You need:

- Docker with Docker Compose v2
- Git

## Start the app

1. Get the code.

   ```bash
   git clone https://github.com/drikusb/empresadence.git
   cd empresadence
   ```

2. Create your settings file from the example.

   ```bash
   cp .env.example .env
   ```

3. Start the stack.

   ```bash
   docker compose up
   ```

   The first start builds the image, so it takes a few minutes. On every start, the container:

   - waits for the database
   - runs the database migrations
   - collects the static files
   - creates a site administrator, if `DJANGO_SUPERUSER_USERNAME` is set and that account does not exist yet

4. Open `http://localhost:8000` in a browser.

   You see the sign-in page.

## Sign in and create your organisation

1. Sign in. With the example settings, the username is `admin` and the password is `adminpass`.

   Because no organisation exists yet, you are sent to the set-up page at `/org/setup/`.

2. Type the name of your organisation and save.

   You are sent to the form for your first team.

3. Type a team name, such as `Leadership`, and save.

4. Open the team from the **Teams** page. Under **Update members**, tick your own username and select **Save members**.

   The navigation bar now shows your team. You can create Priorities, Actions and Blockers.

To add more people, see [Invite a person and set their role](../how-to/invite-a-person.md).

## Email in development

With the example settings, no email is sent. Each email is printed to the container log. Look there for invitation and password links.

```bash
docker compose logs web
```

## Run the tests

```bash
docker compose exec web python manage.py test apps
```

To measure coverage:

```bash
docker compose exec web coverage run manage.py test apps
docker compose exec web coverage report
```

## Stop the app

Press Ctrl+C in the terminal where it is running. Your data stays in a Docker volume. To delete the data too, run `docker compose down -v`.
