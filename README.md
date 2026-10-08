# UK poll chart → Bluesky bot

A tiny bot that watches the Wikipedia/Wikimedia Commons UK opinion-polling chart
and posts it to Bluesky whenever a new poll changes it. It runs for free on
GitHub Actions — there is no server to maintain.

It watches this file:
**[Opinion polling graph for the next United Kingdom general election (post-2024).svg](https://commons.wikimedia.org/wiki/File:Opinion_polling_graph_for_the_next_United_Kingdom_general_election_(post-2024).svg)**

## How it works

Every hour the bot asks the Wikimedia Commons API whether the file has changed.
If it has, it downloads a PNG that **Wikimedia itself renders** from the SVG
(so there's no fragile SVG-to-PNG conversion on our side), checks it fits
Bluesky's 1 MB image limit, and posts it with full attribution. It remembers
the version it last posted in `state/last_sha1.txt`, so it never posts the same
chart twice.

Author and licence are read **live** from the file's own metadata, so the
credit stays correct automatically.

---

## Setup (about 10 minutes)

### 1. Create the Bluesky account and an app password

1. Sign up for the Bluesky account the bot will post from.
2. Create an **app password** (never use your real password in code):
   go to **<https://bsky.app/settings/app-passwords>**
   (or in the app: **Settings → Privacy and Security → App Passwords**),
   click **Add App Password**, give it a name (e.g. "poll-bot"), and
   **copy the password** — Bluesky shows it only once. It looks like
   `xxxx-xxxx-xxxx-xxxx`.
3. Note the account's **handle** (e.g. `ukpolltracker.bsky.social`).

### 2. Put this code in a GitHub repository

Create a new repository (public is simplest and keeps Actions free) and upload
the contents of this folder, keeping the structure:

```
post_chart.py
requirements.txt
state/last_sha1.txt
.github/workflows/post-chart.yml
```

### 3. Add your Bluesky credentials as repository secrets

In the repository: **Settings → Secrets and variables → Actions → Secrets tab
→ New repository secret**. Add two secrets:

| Name            | Value                                   |
| --------------- | --------------------------------------- |
| `BSKY_HANDLE`   | your bot's handle, e.g. `name.bsky.social` |
| `BSKY_PASSWORD` | the **app password** from step 1        |

### 4. Allow the workflow to save its state

The bot commits a one-line state file back to the repo so it remembers what it
last posted. Enable that once: **Settings → Actions → General → Workflow
permissions → "Read and write permissions" → Save**.

### 5. Make the first post

From the **Actions** tab, open **"Post UK poll chart to Bluesky"**, click
**Run workflow**, tick **force**, and run it. That posts the current chart and
records its version. After that, the hourly schedule takes over and only posts
when the chart actually changes.

> On a normal (non-forced) first run the bot records the current version
> *without* posting, so installing it doesn't fire off a post for an update that
> already happened.

---

## Changing how often it checks

Edit the `cron` line in `.github/workflows/post-chart.yml`. It's currently
hourly (`23 * * * *`). The chart updates only a few times a week, so hourly is
plenty; you could relax it to every few hours (`23 */3 * * *`) if you prefer.
(Scheduled runs on GitHub's free tier can be delayed by a while when GitHub is
busy — fine for this use.)

---

## Licence compliance (CC BY-SA)

The chart is licensed **CC BY-SA** (the exact version is read from the file and
shown in each post — it's currently CC BY-SA 4.0). Reposting it is fine as long
as you **attribute** it and keep the derivative under the **same licence**
(ShareAlike). The bot handles this for you:

- **Each post** links to the Wikimedia Commons file page (which carries the
  author list and licence) and names the licence.
- **The alt text of every image** carries the full credit: title, author,
  source URL, licence + link, and a note that the SVG was converted to PNG (a
  "change"), plus a statement that the posted image is under the same licence.
- You should also put a standing credit in the **bot's bio** (below), which
  covers the whole feed.

### Suggested bio for the bot account

> 🤖 Auto-posts the Wikipedia UK general-election poll tracker whenever it
> updates. Chart © Wikipedia contributors, CC BY-SA 4.0, from Wikimedia
> Commons; posted here as PNG under the same licence. Not affiliated with
> Wikipedia. Source: [link to this GitHub repo]

(If you'd rather keep the bio short, the essentials are: *"Chart by Wikipedia
contributors, CC BY-SA 4.0, via Wikimedia Commons — reshared under the same
licence."* The per-image alt text already carries the complete attribution.)

A couple of good-practice notes (not strictly required, but kind and clear):
- Say the account is **unofficial / not affiliated with Wikipedia**, so nobody
  assumes it's an official feed.
- Keep the Commons link intact in posts so readers can reach the authors and
  the exact licence terms.

---

## Running it locally (optional, to test)

```bash
pip install -r requirements.txt
export BSKY_HANDLE="name.bsky.social"
export BSKY_PASSWORD="xxxx-xxxx-xxxx-xxxx"
export FORCE_POST=1          # post regardless of whether it changed
python post_chart.py
```

## Configuration reference (environment variables)

| Variable            | Default                         | Purpose                                        |
| ------------------- | ------------------------------- | ---------------------------------------------- |
| `BSKY_HANDLE`       | *(required)*                    | Bot account handle                             |
| `BSKY_PASSWORD`     | *(required)*                    | Bluesky **app password**                       |
| `FORCE_POST`        | *(off)*                         | `1` to post even if unchanged                  |
| `POST_ON_FIRST_RUN` | `false`                         | `true` to also post on the first ever run      |
| `THUMB_WIDTH`       | `2000`                          | Width of the rendered PNG                      |
| `FILE_TITLE`        | the post-2024 chart            | Point it at a different Commons file           |
| `STATE_FILE`        | `state/last_sha1.txt`           | Where the last-posted version is remembered    |
