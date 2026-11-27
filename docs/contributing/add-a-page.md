---
description: Where a new documentation page goes, what it must contain, and how to check it before you open a pull request.
---

# Add a page

## Before you start

- Read the [style guide](style-guide.md).
- You need Docker to build and check the docs. Nothing else is installed on your computer.

## Choose the right section

The docs follow the Diátaxis system. It sorts pages by what the reader needs at that moment.

| The reader wants to | Section | Folder |
|---|---|---|
| Learn by doing, with a guide | Tutorials | `docs/tutorials/` |
| Get one task done | How-to guides | `docs/how-to/` |
| Look up a fact | Reference | `docs/reference/` |
| Understand how or why | Explanation | `docs/explanation/` |
| Install or run the server | Hosting | `docs/hosting/` |

Keep to one topic for each page. If a how-to guide starts to explain why, move that part to an explanation page and link to it.

## Create the file

1. Create a Markdown file in the folder. Name it in lower case with hyphens, such as `hand-over-a-blocker.md`.

2. Start it with a description and one level 1 heading.

   ```markdown
   ---
   description: One line that says what the page helps you do.
   ---

   # Hand a Blocker to another team
   ```

3. For a how-to guide, add **Before you start**, the numbered steps, and **What happens next**. Copy the shape of an existing guide.

## Add it to the navigation

1. Open `index.md` in the same folder.

2. Add a link to your page in the list.

3. Add the file name, without `.md`, to the `toctree` block at the bottom.

A page that is in no `toctree` fails the build.

## Add stable anchors

If another page links to one of your headings, give the heading a name that stays the same. Put it on the line above the heading:

```markdown
(health-check)=
## Health check
```

Link to it from any page with `[the health check](#health-check)`.

## Check your work

Run these from the top of the repository. `docs/README.md` explains each one.

1. Build the docs. Warnings count as errors.

   ```bash
   docker run --rm -v "$PWD":/work -w /work python:3.15-slim sh -c \
     "pip install -q -r docs/requirements.txt && sphinx-build -W --keep-going -b html docs docs/_build/html"
   ```

2. Check the writing with Vale.

   ```bash
   docker run --rm -v "$PWD":/work -w /work jdkato/vale:v3.29.0 sync
   docker run --rm -v "$PWD":/work -w /work jdkato/vale:v3.29.0 --glob='!**/_build/**' docs
   ```

3. Check the images.

   ```bash
   docker run --rm -v "$PWD":/work -w /work python:3.15-slim python docs/_tools/check_images.py
   ```

4. Open `docs/_build/html/index.html` in a browser and read your page.

## What happens next

Open a pull request. The **Docs** workflow builds the docs, runs Vale and checks the links. Fix any errors it reports.
