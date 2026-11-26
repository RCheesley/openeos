# Empresadence documentation

The source of the documentation site. Pages are MyST Markdown, built with Sphinx and the Furo theme, and checked with Vale.

Start reading at [index.md](index.md). To contribute, read the [style guide](contributing/style-guide.md) and [Add a page](contributing/add-a-page.md).

Everything below runs in Docker from the top of the repository. Nothing is installed on your computer.

## Build the docs

```bash
docker run --rm -v "$PWD":/work -w /work python:3.15-slim sh -c \
  "pip install -q -r docs/requirements.txt && sphinx-build -W --keep-going -b html docs docs/_build/html"
```

Open `docs/_build/html/index.html` in a browser. A warning fails the build.

The build also writes, at the root of the site:

- `llms.txt`, an index of every page with its description
- `llms-full.txt`, every page in one Markdown file
- a `.md` copy of each page beside its `.html`

## Check the links

```bash
docker run --rm -v "$PWD":/work -w /work python:3.15-slim sh -c \
  "pip install -q -r docs/requirements.txt && sphinx-build -b linkcheck docs docs/_build/linkcheck"
```

## Check the writing with Vale

```bash
docker run --rm -v "$PWD":/work -w /work jdkato/vale:v3.29.0 sync
docker run --rm -v "$PWD":/work -w /work jdkato/vale:v3.29.0 --glob='!**/_build/**' docs
```

The first command fetches the Google style package into `docs/.vale/styles/Google/`. That folder is not committed. The package version is pinned in `.vale.ini`. The house rules are committed, in `docs/.vale/styles/Empresadence/`.

The `--glob` option skips the built site, which holds a copy of every page.

Errors must be fixed. Warnings and suggestions are advice.

For an editor, use `vale-ls`, the Vale language server.

## Check the images

```bash
docker run --rm -v "$PWD":/work -w /work python:3.15-slim python docs/_tools/check_images.py
```

## Regenerate the screenshots

The screenshots come from a scripted run against a throwaway copy of the app, loaded with invented "Harbour Lights" demo data. See [Screenshots](contributing/screenshots.md) for the rules.

Run these from the top of the repository. They build the app image, start a database that keeps nothing, load the demo data, take the pictures, and remove everything again.

```bash
docker build --target development -t epd-docs-app .
docker network create epd-docs-net
docker run -d --name epd-docs-db --network epd-docs-net --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_DB=docs -e POSTGRES_USER=docs -e POSTGRES_PASSWORD=docs postgres:15-alpine
docker run -d --name epd-docs-web --network epd-docs-net -v "$PWD":/app \
  -e DJANGO_SETTINGS_MODULE=config.settings.development -e SECRET_KEY=docs-throwaway \
  -e DB_NAME=docs -e DB_USER=docs -e DB_PASSWORD=docs -e DB_HOST=epd-docs-db -e DB_PORT=5432 \
  -e ALLOWED_HOSTS='*' epd-docs-app /app/entrypoint.sh python manage.py runserver 0.0.0.0:8000

# Wait until the log says the development server has started.
docker logs -f epd-docs-web

docker exec -i epd-docs-web python manage.py shell < docs/_tools/seed_demo.py
docker run --rm --network epd-docs-net -v "$PWD/docs":/docs -w /docs/_tools \
  mcr.microsoft.com/playwright/python:v1.65.2-noble sh -c \
  "pip install -q playwright==1.65.2 pillow==13.0.0 && python capture_screenshots.py --base-url http://epd-docs-web:8000"

docker rm -f epd-docs-web epd-docs-db
docker network rm epd-docs-net
```

The run changes data as it goes. To run it again, empty the database first:

```bash
docker exec epd-docs-web python manage.py flush --noinput
```

Then check the result:

```bash
docker run --rm -v "$PWD":/work -w /work python:3.15-slim python docs/_tools/check_images.py
```

## Layout

| Path | What it holds |
|---|---|
| `index.md`, `agents.md` | The front page and the page for AI agents |
| `tutorials/`, `how-to/`, `reference/`, `explanation/` | The four kinds of page |
| `hosting/` | Installing, deploying and upgrading |
| `contributing/` | The style guide and how to add a page |
| `_static/screenshots/` | Screenshots, made by script |
| `_tools/` | The demo data, the screenshot script, its manifest and the image check |
| `_ext/` | A small Sphinx extension: descriptions, `llms.txt`, screenshot sizes |
| `.vale/styles/Empresadence/` | The house rules for Vale |
| `conf.py`, `requirements.txt`, `Makefile` | Sphinx configuration, pinned tools and build targets |
