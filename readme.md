# Flask app for Prolific experiments

The app serves a consent page and assigns one CSV row to each participant submission. A row can contain multiple stimuli and can be allocated to several independent participants. The bundled CSV and questionnaire show one example. Run the following commands in the app directory, which is also where the app reads its files and writes its results.

## Prepare a study

| File | What to configure |
|---|---|
| `data.csv` | Use a header and one row per allocatable task. Column names must match the placeholders in your questionnaire. |
| `templates/interface.html` | Supply the study instructions, stimuli, inputs, answer validation and submission handler. The bundled example's 32 items, timers and practice checks are specific to that questionnaire. |
| `templates/consent.html` | Edit the text in your supplied consent form, then save it here. The app displays it before allocating a task. |
| `CreateDatabase.py` | Set `NUMBER_OF_TASKS` to the number of CSV data rows and `COMPLETIONS_PER_TASK` to the number of independent assignments per row. |

### Questionnaire

Use `${column_name}` in HTML text for CSV values and `${task_id}` for the assignment UUID. The app escapes substituted values for HTML text and adds hidden inputs with IDs `prolific_pid` and `session_id`. On submission, POST a JSON object to `/` containing `task_id`, `prolific_pid`, `session_id` and your answer fields. The interface defines which answers must be complete. Redirect to the study's actual Prolific completion URL only after HTTP 200 and JSON `{"result":"OK"}`. The URL in the example is a placeholder. If receipt is uncertain, retry the same payload.

<details>
<summary>Writing a consent form from scratch</summary>

The consent page is served as plain HTML. Submit a form to the current URL using `method="post"` and omit the `action` attribute so the Prolific query parameters are preserved. Required acknowledgements can be checkboxes named `consent_ack`, each with a distinct value and the `required` attribute. The server checks the acknowledgements it offered to that browser. Include both decision controls inside the form:

```html
<button type="submit" name="decision" value="accept">I consent and wish to continue</button>
<button type="submit" name="decision" value="decline" formnovalidate>Decline and leave</button>
```

Accepting records consent in the signed browser session. Declining ends the flow before allocation. The session cookie requires HTTPS. A study that requires a durable consent receipt must arrange for that separately.

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
.venv/bin/gunicorn --bind "127.0.0.1:${PORT:-8101}" --workers 1 --threads 4 --access-logfile /dev/null main:app
```

One worker runs the in-process expiry scheduler. For a public study, configure an HTTPS reverse proxy to the loopback listener. Configure your service manager to use the study directory as its working directory, load the same environment and start Gunicorn after a reboot. Keep secrets and full request URLs out of logs. The app uses local SQLite and filesystem storage.

## Participant and researcher URLs

Configure the external Prolific study to send participants to `https://YOUR_HOST/study/` with the URL parameters `PROLIFIC_PID`, `STUDY_ID` and `SESSION_ID`. A bare participant URL without identifiers returns 400.

Each researcher URL below takes `?code=YOUR_CODE`:

| Path | Purpose |
|---|---|
| `/row/0` | Preview CSV row zero without allocating it. |
| `/tasksallocated` | Inspect assignment status and participant/session IDs. |
| `/results/TASK_UUID` | Inspect one saved result. |
| `/abdn` | Release expired assignments now and list tasks. |

The allocator claims waiting copies in database order, skips rows already allocated to or completed by the same participant, and resumes the assignment on refresh. Unsubmitted answers can be lost on refresh.

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
