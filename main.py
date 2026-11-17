"""Serve one lab's Prolific experiment from its working directory."""
import hmac
import json
import os
import re
import sqlite3
import tempfile
from functools import wraps
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from uuid import UUID

import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, abort, redirect, render_template_string, request, session

import DataManager as dm

MAX_TIME = int(os.environ.get("MAX_TIME", "3600"))
df = pd.read_csv('data.csv')
app = Flask(__name__)
app.config.update(SECRET_KEY=os.environ["FLASK_SECRET_KEY"], SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=True)
if not app.secret_key:
    raise RuntimeError("Set a nonempty FLASK_SECRET_KEY for this lab.")
ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
TOKEN = re.compile(r"\$\{([\w.-]+)\}")


class ConsentAcknowledgements(HTMLParser):
    """Read the required acknowledgements from the form actually offered."""
    def __init__(self):
        super().__init__()
        self.values = []

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if (tag == "input" and fields.get("type") == "checkbox"
                and fields.get("name") == "consent_ack" and "required" in fields):
            self.values.append(fields.get("value", "on"))


def researcher_only(view):
    @wraps(view)
    def protected(*args, **kwargs):
        code = os.environ.get("LAB_ADMIN_CODE", "")
        supplied = request.args.get("code", "")
        if not code or not hmac.compare_digest(code.encode(), supplied.encode()):
            abort(404)
        return view(*args, **kwargs)
    return protected


@app.after_request
def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def task_page(row_index, task_id, participant=None):
    if not 0 <= row_index < len(df):
        abort(404)
    # Only lab-authored template text is evaluated as Jinja.
    template = render_template_string(Path('templates/interface.html').read_text())
    values = df.iloc[row_index].to_dict()
    values["task_id"] = task_id
    page = TOKEN.sub(lambda m: escape(str(values[m[1]]), quote=True)
                     if m[1] in values else m[0], template)
    if participant:
        pid, sid, _ = participant
        page += (f'<input type="hidden" id="prolific_pid" value="{escape(pid)}">'
                 f'<input type="hidden" id="session_id" value="{escape(sid)}">')
    return page


@app.route('/study/', methods=['GET', 'POST'])
def study():
    pid = request.args.get('PROLIFIC_PID', '')
    sid = request.args.get('SESSION_ID', '')
    study_id = request.args.get('STUDY_ID', '')
    if not ID.fullmatch(pid) or not ID.fullmatch(sid) or (study_id and not ID.fullmatch(study_id)):
        abort(400, "Please open the study using your Prolific link.")
    expected_study = os.environ.get("PROLIFIC_STUDY_ID")
    if expected_study and study_id != expected_study:
        abort(400, "This link belongs to a different study.")
    participant = [pid, sid, study_id]
    if request.method == "POST":
        if session.get("offered") != participant:
            abort(403, "Please reopen the consent form using your Prolific link.")
        decision = request.form.get("decision")
        if decision not in ("accept", "decline"):
            abort(400, "Select a consent decision.")
        if decision == "accept":
            offered = set(session.get("consent_ack", []))
            if not offered.issubset(request.form.getlist("consent_ack")):
                abort(400, "Please return to the form to review each consent statement.")
        session.clear()
        if decision == "decline":
            return "You have declined to participate. You can now return the study on Prolific."
        session["consented"] = participant
        return redirect(request.full_path, code=303)

    if session.get("consented") != participant:
        consent = Path("templates/consent.html")
        if not consent.is_file():
            abort(503, "The consent form is not yet available. Please contact the lab.")
        session.clear()
        session["offered"] = participant
        page = consent.read_text()
        checks = ConsentAcknowledgements()
        checks.feed(page)
        session["consent_ack"] = checks.values
        return page
    try:
        task = dm.allocate_task(pid, sid)
    except sqlite3.Error:
        app.logger.exception("Task allocation failed")
        abort(503, "Unable to open the task. Please try again.")
    if task is None:
        return "No tasks available. Please contact the lab through Prolific.", 409
    task_id, task_number = task
    return task_page(task_number - 1, task_id, participant)


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == "GET":
        return "Nothing Here."
    answers = request.get_json()
    if not isinstance(answers, dict):
        abort(400)
    task_id = answers.get("task_id")
    try:
        if not isinstance(task_id, str) or str(UUID(task_id)) != task_id:
            abort(400)
    except ValueError:
        abort(400)
    participant = session.get("consented")
    if not participant or participant[:2] != [answers.get("prolific_pid"), answers.get("session_id")]:
        abort(403, "Please reopen the study from Prolific in the same browser.")
    try:
        if not dm.complete_task(task_id, answers, *participant[:2]):
            abort(409, "This response does not match the assignment or its saved answers.")
        # Keep the original JSON export. If disk I/O fails, an identical retry
        # can repair the export from the already committed submission.
        directory = Path("data") / task_id
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, delete=False, mode="w") as tmp:
            try:
                json.dump(answers, tmp)
                tmp.close()
                os.replace(tmp.name, directory / f"{task_id}.json")
            finally:
                Path(tmp.name).unlink(missing_ok=True)
    except (OSError, sqlite3.Error):
        app.logger.exception("Saving the submission failed")
        return {"result": "Unable to confirm save. Retry with the same answers."}, 503
    return {"result": "OK"}


@app.route('/row/<int:row_id>', methods=['GET', 'POST'])
@researcher_only
def row(row_id):
    return task_page(row_id, row_id)


@app.get('/tasksallocated')
@researcher_only
def allocated():
    return dm.get_all_tasks()


@app.get('/results/<task_id>')
@researcher_only
def results(task_id):
    result = dm.get_specific_result(task_id)
    if result is None:
        abort(404)
    return app.response_class(str(result), mimetype="text/plain")


@app.get('/abdn')
@researcher_only
def check_abandonment():
    dm.expire_tasks(MAX_TIME)
    return dm.get_all_tasks()


scheduler = BackgroundScheduler()
scheduler.add_job(dm.expire_tasks, "interval", seconds=MAX_TIME, args=[MAX_TIME])
scheduler.start()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8101")))
