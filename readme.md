# Run MTurk-style HTML tasks with Flask and Prolific

This Flask app hosts tasks in the style of Amazon Mechanical Turk (MTurk) and recruits participants through Prolific. As with an MTurk HTML task, you supply a questionnaire template and a CSV of inputs. Each row defines one task, and you choose how many different participants can complete it. Prolific sends participants to the app. Flask collects consent, assigns a task, fills in the template and saves the answers. The questionnaire then sends the participant back to Prolific.

Clone the app’s `main` branch into a study directory on a host with Python 3 and virtual environment support. Run the setup commands from that directory. The app reads its study files and writes its results there.

```bash
git clone --branch main https://github.com/nlgcat/prolific-html-webapp.git my-study
cd my-study
```

## Prepare a study

| File | What to configure |
|---|---|
| `data.csv` | Use a header and one row per allocatable task. Column names must match the placeholders in your questionnaire. |
| `templates/interface.html` | Adapt the bundled questionnaire or supply your own HTML with participant instructions, input fields, validation and a submission handler. |
| `templates/consent.html` | Save your study’s consent form here. The app displays it before allocating a task. See the form requirements below. |
| `CreateDatabase.py` | Set `NUMBER_OF_TASKS` to the number of CSV data rows and `COMPLETIONS_PER_TASK` to the number of independent assignments per row. |

### Questionnaire

For example, a CSV with a column named `prompt` can supply the text for `<p>${prompt}</p>` in your questionnaire. A row containing `Choose a title for this image` will display that instruction. Use the column names and answer fields your own task needs.

Use `${column_name}` in HTML text for CSV values and `${task_id}` for the assignment UUID. The app escapes substituted values for HTML text and adds hidden inputs with IDs `prolific_pid` and `session_id`. On submission, POST a JSON object to `/` containing `task_id`, `prolific_pid`, `session_id` and your answer fields. The interface defines which answers must be complete. Redirect to the study's actual Prolific completion URL only after HTTP 200 and JSON `{"result":"OK"}`. The URL in the example is a placeholder. If receipt is uncertain, retry the same payload.

<details>
<summary>Writing a consent form from scratch</summary>

The consent page is served as plain HTML. Submit a form to the current URL using `method="post"` and omit the `action` attribute so the Prolific query parameters are preserved. Required acknowledgements can be checkboxes named `consent_ack`, each with a distinct value and the `required` attribute. The server checks the acknowledgements it offered to that browser. Include both decision controls inside the form:

```html
<button type="submit" name="decision" value="accept">I consent and wish to continue</button>
<button type="submit" name="decision" value="decline" formnovalidate>Decline and leave</button>
```

Accepting records consent in the signed browser session. Declining ends the flow before allocation. A study that requires a durable consent receipt must arrange for that separately.

</details>

## Install and configure the server

Create a Python virtual environment and install the dependencies:

```bash
umask 077
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

The app reads environment variables at startup. You can keep them in a private, shell-compatible file in your study directory. This example creates `study.env` once and refuses to overwrite an existing file:

```bash
( set -C; umask 077; cat > study.env <<EOF_ENV
PORT=8101
MAX_TIME=3600
PROLIFIC_STUDY_ID=REPLACE_WITH_DRAFT_ID
LAB_ADMIN_CODE=$(openssl rand -hex 16)
FLASK_SECRET_KEY=$(openssl rand -hex 32)
EOF_ENV
)
```

| Variable | Meaning |
|---|---|
| `PORT` | Local listening port. The default is `8101`. |
| `SESSION_COOKIE_SECURE` | Leave unset for HTTP. Set to `1` for an HTTPS-only site. |
| `MAX_TIME` | Assignment lifetime in seconds. Default `3600`. Cleanup runs periodically at this interval. |
| `PROLIFIC_STUDY_ID` | Allowed Prolific study ID. Set it to the current draft or posting so links from other postings are rejected. |
| `LAB_ADMIN_CODE` | Private code for researcher URLs. Without a configured code those routes return 404. |
| `FLASK_SECRET_KEY` | Required signing key for consent sessions. Keep it private and stable across restarts. |

After configuring the CSV and task counts, initialize the database **once in a fresh study directory**. The initializer checks the row count and refuses to overwrite an existing database:

```bash
.venv/bin/python CreateDatabase.py
```

To start the app, load the configuration into the environment and run Gunicorn from the same directory:

```bash
set -a
. ./study.env
set +a
.venv/bin/gunicorn --bind "0.0.0.0:${PORT:-8101}" --workers 1 --threads 4 --access-logfile /dev/null main:app
```

This serves HTTP directly. Allow inbound TCP on the chosen port so participants can reach it. HTTP sends participant IDs, session cookies, responses and any researcher codes used over that connection in clear text. For an HTTPS deployment, bind Gunicorn to loopback behind your HTTPS reverse proxy and set `SESSION_COOKIE_SECURE=1`.

One worker runs the in-process expiry scheduler. Configure your service manager to use the study directory as its working directory, load the same environment and start Gunicorn after a reboot. Keep secrets and full request URLs out of logs. The app uses local SQLite and filesystem storage.

## Participant and researcher URLs

For direct HTTP, enter `http://YOUR_PUBLIC_IP:8101/study/` as the external study URL in Prolific. Substitute your server’s address and configured port. Include the URL parameters `PROLIFIC_PID`, `STUDY_ID` and `SESSION_ID`. A bare participant URL without identifiers returns 400.

Each researcher URL below takes `?code=YOUR_CODE`:

| Path | Purpose |
|---|---|
| `/row/0` | Preview CSV row zero without allocating it. |
| `/tasksallocated` | Inspect assignment status and participant/session IDs. |
| `/results/TASK_UUID` | Inspect one saved result. |
| `/abdn` | Release expired assignments now and list tasks. |

The allocator claims waiting copies in database order, skips rows already allocated to or completed by the same participant, and resumes the assignment on refresh. Unsubmitted answers can be lost on refresh.

## Running sequential batches

You can use one server, port and participant URL for several Prolific studies. Run one posting at a time. `PROLIFIC_STUDY_ID` checks the incoming study ID. The running app draws tasks from the database in its working directory. Changing the study ID alone leaves the same tasks available.

1. **Prepare one study directory per batch.** Follow the setup above for each directory, with its own `study.env`, questionnaire and `data.csv`. Include the header and the rows for that batch. If you need to match items across exports, keep a stable item identifier in the CSV because task numbers start at 1 in each database. Set `NUMBER_OF_TASKS` to that batch’s row count and `COMPLETIONS_PER_TASK` to the assignments you need per row. Run the initializer once in each directory. The number of available assignments is the product of those two settings.
2. **Open the current posting.** Give each primary Prolific study the same participant URL with the three URL parameters above. In the active directory, set `PROLIFIC_STUDY_ID` to that posting’s ID and set the questionnaire’s completion URL to its Prolific completion URL. Load `study.env` and start Gunicorn from this directory using the commands above. If you use a service manager, set its working directory and environment file to this batch’s paths and restart the service.
3. **Handle replacements if your study uses them.** Once the posting is closed and active submissions have finished, identify any completed responses that need replacing under your study’s rules. For each one, add a waiting assignment for the same item to the active database using the command below. The original response stays in the database, so the allocator can still tell which participants have seen the item. Use the replacement posting’s study ID and completion URL, reload the environment and restart Gunicorn before opening that posting.
4. **Switch batches** once the current batch meets your study’s completion criteria and active submissions have finished. Stop Gunicorn, switch to the next batch’s directory and repeat step 2. The server itself can stay up throughout.

To add replacements for completed responses, run the following in the active batch directory. Replace the example argument with the exported `task_id` of the response to replace. You can pass several IDs separated by spaces. Reusing an ID in this command creates at most one replacement for that response. If a replacement also needs replacing, pass its own task ID.

```bash
.venv/bin/python - REPLACE_WITH_COMPLETED_TASK_ID <<'PY'
import sqlite3
import sys
import uuid

with sqlite3.connect("file:database.db?mode=rw", uri=True) as db:
    for original in sys.argv[1:]:
        row = db.execute(
            "SELECT task_number FROM tasks WHERE id=? AND status='completed'", (original,)
        ).fetchone()
        if row is None:
            raise SystemExit(f"No completed assignment {original} in this batch")
        replacement = str(uuid.uuid5(uuid.UUID(original), "replacement"))
        db.execute(
            "INSERT INTO tasks (id, task_number, status) VALUES (?, ?, 'waiting') "
            "ON CONFLICT(id) DO NOTHING", (replacement, row[0])
        )
PY
```

## Access saved results

SQLite stores results in `database.db`. The app also writes `data/<task_id>/<task_id>.json`. A database task number is the **one-based** CSV row number. You can inspect status, export responses and take a consistent SQLite backup with:

```bash
umask 077
sqlite3 -readonly database.db 'SELECT status,count(*) FROM tasks GROUP BY status;'
sqlite3 -readonly -header -csv database.db \
  "SELECT t.task_number,t.id AS task_id,t.prolific_id,t.session_id,r.json_string AS answers FROM tasks t JOIN results r ON r.id=t.id WHERE t.status='completed';" > responses.csv
sqlite3 database.db ".backup 'study-backup.db'"
sqlite3 -readonly study-backup.db 'PRAGMA integrity_check; SELECT count(*) FROM results;'
```

New submissions store JSON in `results.json_string`. Earlier versions used Python dictionary strings. Keep the original CSV, interface, consent HTML and study settings alongside the backup so the responses can be interpreted.
