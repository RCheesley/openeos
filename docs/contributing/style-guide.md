---
description: The writing rules for the Empresadence docs. British spelling, sentence-case headings, short sentences, exact interface labels and the default vocabulary. Vale checks most of them.
---

# Style guide

These docs have two readers. One is a person in a small business who is not technical. The other is a person or an AI agent who installs, runs or changes Empresadence. Both are helped by the same thing: short, exact, plain writing.

A tool called Vale checks most of these rules. See [Check your writing with Vale](#check-with-vale).

## Language

- **Use British spelling.** Write "organisation", "colour", "licence" (the noun) and "centre". Vale checks every word against a British English dictionary.
- **Write to "you", in the present tense, in the active voice.** Write "Select **Save**. You see the list." Do not write "The Save button should be clicked, after which the list is shown."
- **Put one idea in each sentence.** If a sentence has "and" or "which" in the middle, try two sentences.
- **Use plain words.** If you must use a technical word, say what it means the first time.
- **Write "for example", "that is" and "and so on".** Do not use the Latin short forms.
- **Do not use em dashes.** Use a full stop, a comma or brackets.
- **Write dates as 26 November 2026.**

## Words to avoid

<!-- vale Empresadence.Filler = NO -->

| Do not write | Why |
|---|---|
| "simply", "just", "easy", "obviously" | They add nothing. They make a reader who is stuck feel worse |
| `silently`, `silent`, `quietly` | Say what happens and what the reader sees instead |
| `honest`, `honestly`, `genuine`, `genuinely` | They suggest the rest is not |

<!-- vale Empresadence.Filler = YES -->

(vocabulary-rule)=
## Product vocabulary

Empresadence lets each organisation rename its building blocks. The docs always use the default words, exactly, with a capital letter:

Priority, Step, Action, Blocker, Metrics Board, Weekly Meeting, Vision and Delivery Board, Org Chart, Role, Value, Update, Check-in, PSR, Key Message.

The defaults live in `apps/accounts/terminology.py`. The [glossary](../reference/glossary.md) says what each one means.

When a page uses these words, add this sentence once, near the top:

> Your organisation may have renamed some words. This page uses the default names. See the [glossary](../reference/glossary.md).

### Words that must not appear

This project removed a set of trademarked words from its interface. They must not come back in the docs. `TRADEMARK-REMEDIATION.md` at the top of the repository tells the story and has the full list. Vale reports each of these as an error:

`Rock`, `Scorecard`, `Level 10`, `VTO`, `V/TO`, `Traction`, `IDS`, `Accountability Chart`, `Segue`, `Headline`, `Cascading Message`, `Seat`, `Core Value`, `Core Focus`, `Milestone`, `Visionary`, `Integrator`, `EOS`.

Some of these still appear in the code as names of files, models and addresses, such as `/rocks/`. That is fine. Put them in code formatting, as here, and Vale leaves them alone.

## Headings

- **Use sentence case.** Capitalise the first word and product terms only. Write "Add and complete an Action", not "Add And Complete An Action".
- **Make each heading describe what is under it.** A reader should be able to find a section from the list of headings alone.
- **Do not skip levels.** A page has one level 1 heading. Level 3 comes only under level 2.

## Procedures

- **Number the steps.** Use a numbered list for anything the reader does in order.
- **Put one action in each step.**
- **Copy interface labels exactly, in bold.** Write **Create Action**, with the same capitals as on screen, even where the screen uses American spelling. Vale does not check text in bold.
- **Say what the reader sees after a step.** For example: "You see the **Actions** page. A green message confirms the Action was created."
- **Give the address as well as the menu path.** Write "Select **Actions**, then **New Action**. The address is `/todos/new/`." A program can use the address. A person can use the menu.

Every how-to guide has the same shape:

1. One or two sentences on what the task is.
2. **Before you start**: the role needed, and anything to have ready.
3. The numbered steps.
4. **What happens next**: what changes as a result, and where to go from here.

## Links

- **Make link text describe the destination.** Write "see [Roles and what each can do](../reference/roles.md)". Do not write "click here".
- **Link to the Markdown file.** Write `[text](../reference/roles.md)`. The link then works on GitHub and on the built site.

## Images

- **Put each screenshot directly under the step it shows.**
- **Give every image alt text.** Say what the picture shows, in a full sentence. A reader who cannot see it should lose nothing.
- **Never put information only in an image.** Anything the reader needs must also be in the text.
- **Do not take screenshots by hand.** See [Screenshots](screenshots.md).

## Facts

- **Check every statement about behaviour** against the running app or the code. If you are not sure, leave it out.
- **Use tables for reference data**, such as roles, settings and options.

## Front matter

Every page starts with a one-line description:

```markdown
---
description: Add an Action for yourself or a teammate, then mark it complete.
---
```

The description appears in search results and in `llms.txt`. The build fails if a page has none.

(check-with-vale)=
## Check your writing with Vale

[Vale](https://vale.sh/) is a linter for prose. Its configuration is `.vale.ini` at the top of the repository. The house rules are in `docs/.vale/styles/Empresadence/`.

`docs/README.md` has the command to run it.

| Level | Meaning | Examples |
|---|---|---|
| Error | Must be fixed. The docs check fails | A misspelt word, American spelling, a heading not in sentence case, a removed word, a banned word, an em dash, an image with no alt text |
| Warning | Look at it and fix it if you can | Filler words, Latin short forms, a date in another format, vague link text |
| Suggestion | Advice from the Google style rules | Passive voice, long sentences |

If Vale is wrong about one line, switch one rule off around it and say why:

```markdown
<!-- vale Empresadence.Spelling = NO -->
<!-- vale Empresadence.Americanisms = NO -->
The setting is called "Primary color".
<!-- vale Empresadence.Spelling = YES -->
<!-- vale Empresadence.Americanisms = YES -->
```
