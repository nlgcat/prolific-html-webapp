import ast
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def create_connection(db_file='database.db'):
    return sqlite3.connect(db_file, timeout=10)


def available_task(conn, prolific_id):
    """Use the same eligibility rule for allocation and completion messages."""
    return conn.execute("""
        SELECT id, task_number FROM tasks WHERE status='waiting'
        AND task_number NOT IN (
            SELECT task_number FROM tasks WHERE prolific_id=?
            AND status IN ('allocated', 'completed')
        ) ORDER BY rowid LIMIT 1
    """, (prolific_id,)).fetchone()


def allocate_task(prolific_id, session_id):
    """Return the existing assignment for this submission, or claim a waiting copy."""
    with closing(create_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("""
            SELECT id, task_number FROM tasks
            WHERE prolific_id=? AND session_id=? AND status IN ('allocated', 'completed')
        """, (prolific_id, session_id)).fetchone()
        if existing:
            return existing
        task = available_task(conn, prolific_id)
        if task:
            now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")
            conn.execute("""UPDATE tasks SET status='allocated', prolific_id=?,
                            session_id=?, time_allocated=? WHERE id=?""",
                         (prolific_id, session_id, now, task[0]))
        return task


def expire_tasks(time_limit=3600):
    with closing(create_connection()) as conn, conn:
        conn.execute("""UPDATE tasks SET status='waiting', prolific_id=NULL,
                        time_allocated=NULL, session_id=NULL WHERE status='allocated'
                        AND julianday(time_allocated) <= julianday('now') - ? / 86400.0""",
                     (time_limit,))


def complete_task(task_id, answers, prolific_id, session_id):
    """Commit once. An identical retry of a committed submission is successful."""
    with closing(create_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        task = conn.execute("""SELECT status FROM tasks WHERE id=?
                               AND prolific_id=? AND session_id=?""",
                            (task_id, prolific_id, session_id)).fetchone()
        if task == ('completed',):
            saved = conn.execute("SELECT json_string FROM results WHERE id=?", (task_id,)).fetchone()
            if not saved:
                return False
            try:
                original = json.loads(saved[0])
            except json.JSONDecodeError:
                # Earlier versions stored Python dictionary literals.
                original = ast.literal_eval(saved[0])
            if original != answers:
                return False
        elif task == ('allocated',):
            conn.execute("INSERT INTO results (id,json_string,prolific_id) VALUES (?,?,?)",
                         (task_id, json.dumps(answers), prolific_id))
            conn.execute("UPDATE tasks SET status='completed' WHERE id=?", (task_id,))
        else:
            return False
        # Additive upgrade for existing databases. Preserve the completion-time
        # answer on retries, even when other assignments have since changed.
        conn.execute("""CREATE TABLE IF NOT EXISTS completion_availability (
            task_id TEXT PRIMARY KEY, more_tasks_available INTEGER NOT NULL
        )""")
        conn.execute("""INSERT OR IGNORE INTO completion_availability
                        (task_id, more_tasks_available) VALUES (?, ?)""",
                     (task_id, available_task(conn, prolific_id) is not None))
    return True


def completion_has_more_tasks(task_id):
    with closing(create_connection()) as conn:
        row = conn.execute(
            "SELECT more_tasks_available FROM completion_availability WHERE task_id=?",
            (task_id,),
        ).fetchone()
        return bool(row[0])


def claim_no_tasks_completion(prolific_id, session_id, study_id, code, db_file='database.db'):
    """Issue once per participant; the original submission can recover its code."""
    with closing(create_connection(db_file)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""CREATE TABLE IF NOT EXISTS no_tasks_completions (
            prolific_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            study_id TEXT NOT NULL,
            completion_code TEXT NOT NULL,
            issued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("""INSERT OR IGNORE INTO no_tasks_completions
                        (prolific_id, session_id, study_id, completion_code)
                        VALUES (?, ?, ?, ?)""", (prolific_id, session_id, study_id, code))
        row = conn.execute("""SELECT completion_code FROM no_tasks_completions
                              WHERE prolific_id=? AND session_id=? AND study_id=?""",
                           (prolific_id, session_id, study_id)).fetchone()
        return row[0] if row else None


def get_no_tasks_completion(prolific_id, session_id, study_id, db_file='database.db'):
    if not Path(db_file).is_file():
        return None
    with closing(create_connection(db_file)) as conn:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='no_tasks_completions'"
        ).fetchone()
        if not table:
            return None
        row = conn.execute("""SELECT completion_code FROM no_tasks_completions
                              WHERE prolific_id=? AND session_id=? AND study_id=?""",
                           (prolific_id, session_id, study_id)).fetchone()
        return row[0] if row else None


def get_all_tasks():
    with closing(create_connection()) as conn:
        return conn.execute("SELECT * FROM tasks").fetchall()


def get_specific_result(result_id):
    with closing(create_connection()) as conn:
        return conn.execute("SELECT * FROM results WHERE id=?", (result_id,)).fetchone()
