import ast
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone


def create_connection(db_file='database.db'):
    return sqlite3.connect(db_file, timeout=10)


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
        task = conn.execute("""
            SELECT id, task_number FROM tasks WHERE status='waiting'
            AND task_number NOT IN (
                SELECT task_number FROM tasks WHERE prolific_id=?
                AND status IN ('allocated', 'completed')
            ) ORDER BY rowid LIMIT 1
        """, (prolific_id,)).fetchone()
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
            return original == answers
        if task != ('allocated',):
            return False
        conn.execute("INSERT INTO results (id,json_string,prolific_id) VALUES (?,?,?)",
                     (task_id, json.dumps(answers), prolific_id))
        conn.execute("UPDATE tasks SET status='completed' WHERE id=?", (task_id,))
    return True


def get_all_tasks():
    with closing(create_connection()) as conn:
        return conn.execute("SELECT * FROM tasks").fetchall()


def get_specific_result(result_id):
    with closing(create_connection()) as conn:
        return conn.execute("SELECT * FROM results WHERE id=?", (result_id,)).fetchone()
