"""HTTP and SQLite regression checks on a temporary study with the original schema."""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class StudyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        before = Path.cwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, before)
        self.env = patch.dict(os.environ, {"LAB_ADMIN_CODE": "secret", "FLASK_SECRET_KEY": "test-key",
                                          "PROLIFIC_STUDY_ID": "study1",
                                          "NO_TASKS_COMPLETION_CODE": "",
                                          "NO_TASKS_RECEIPTS_DB": "database.db"})
        self.env.start()
        self.addCleanup(self.env.stop)
        shutil.copy(ROOT / "data.csv", ".")
        shutil.copytree(ROOT / "templates", "templates")
        self.consent = Path("templates/consent.html")
        self.consent.write_text('<form method="post">Consent fixture</form>')
        self.initialize()
        import main
        self.main = main
        self.client = main.app.test_client()

    def initialize(self, check=True):
        return subprocess.run([sys.executable, str(ROOT / "CreateDatabase.py")],
                              capture_output=True, check=check)

    @staticmethod
    def link(pid="P1", sid="S1"):
        return f"/study/?PROLIFIC_PID={pid}&SESSION_ID={sid}&STUDY_ID=study1"

    def start(self):
        url = self.link()
        self.assertIn(b"Consent fixture", self.client.get(url).data)
        response = self.client.post(url, data={"decision": "accept"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        return re.search(rb'id="task_id">([^<]+)', response.data)[1].decode()

    def test_consent_and_identifiers(self):
        url = self.link()
        self.assertEqual(self.client.post(url, data={"decision": "accept"}).status_code, 403)
        self.assertEqual(self.client.get(self.link("<bad>")).status_code, 400)
        self.assertEqual(self.client.get(url.replace("study1", "wrong")).status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertIn(b"declined", self.client.post(url, data={"decision":"decline"}).data)
        self.assertTrue(all(t[-1] == "waiting" for t in self.main.dm.get_all_tasks()))
        self.consent.unlink()
        self.assertEqual(self.client.get(url).status_code, 503)

    def test_http_and_https_session_cookie(self):
        from http.cookies import SimpleCookie

        # Import the app in a fresh process for each startup configuration.
        probe = (
            "from main import app\n"
            f"response = app.test_client().get({self.link()!r})\n"
            "print(response.headers['Set-Cookie'])"
        )
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        env.pop("SESSION_COOKIE_SECURE", None)
        for secure in (False, True):
            if secure:
                env["SESSION_COOKIE_SECURE"] = "1"
            header = subprocess.check_output([sys.executable, "-c", probe], env=env, text=True)
            cookie = SimpleCookie(header.strip())["session"]
            self.assertEqual(bool(cookie["secure"]), secure)
            self.assertTrue(cookie["httponly"])
            self.assertEqual(cookie["samesite"], "Lax")

    def test_consent_form_requires_each_acknowledgement(self):
        self.consent.write_text(
            '<form method="post">'
            '<input type="checkbox" name="consent_ack" value="information" required>'
            '<input type="checkbox" name="consent_ack" value="participate" required>'
            '</form>'
        )
        url = self.link()
        form = self.client.get(url)
        required = re.findall(r'name="consent_ack" value="([^"]+)" required', form.text)
        self.assertEqual(required, ["information", "participate"])
        for missing in required:
            response = self.client.post(url, data={"decision": "accept", "consent_ack":
                                        [value for value in required if value != missing]})
            self.assertEqual(response.status_code, 400)
        self.assertTrue(all(task[-1] == "waiting" for task in self.main.dm.get_all_tasks()))
        self.assertEqual(self.client.post(url, data={"decision": "accept",
                                                     "consent_ack": required}).status_code, 303)

    def test_researcher_code_and_csv_rows(self):
        routes = ("/tasksallocated", "/row/0", "/abdn", "/results/unknown")
        for path in routes:
            self.assertEqual(self.client.get(path).status_code, 404)
            self.assertEqual(self.client.get(path+"?code=wrong").status_code, 404)
        with patch.dict(os.environ, {"LAB_ADMIN_CODE": ""}):
            self.assertEqual(self.client.get("/tasksallocated?code=secret").status_code, 404)
        self.assertEqual(self.client.get("/tasksallocated?code=secret").status_code, 200)
        self.assertEqual(self.client.get("/abdn?code=secret").status_code, 200)
        key = self.start()
        self.assertIn(key.encode(), self.client.get(self.link()).data)
        from html import escape
        for i in (0,59):
            snippet = escape(str(self.main.df.iloc[i]["input0"])).encode()
            self.assertIn(snippet, self.client.get(f"/row/{i}?code=secret").data)
            with patch.object(self.main.dm, "allocate_task", return_value=(key, i + 1)):
                self.assertIn(snippet, self.client.get(self.link()).data)
        with patch.object(self.main.dm, "allocate_task", return_value=None):
            self.assertEqual(self.client.get(self.link()).status_code, 409)

    def test_submission_retries_and_failures(self):
        key = self.start()
        payload = dict(task_id=key, prolific_pid="P1", session_id="S1", score=2)
        save = lambda obj: self.client.post("/", json=obj)
        self.assertEqual(save(dict(payload, task_id="../other")).status_code, 400)
        self.assertEqual(save(dict(payload, session_id="wrong")).status_code, 403)
        self.assertEqual(self.main.app.test_client().post("/", json=payload).status_code, 403)
        with patch.object(self.main.dm, "complete_task", side_effect=sqlite3.OperationalError("test failure")):
            self.assertEqual(save(payload).status_code, 503)
        self.assertFalse(Path("data").exists())
        with patch("main.os.replace", side_effect=OSError("test disk failure")):
            self.assertEqual(save(payload).status_code, 503)
        for _ in range(2):
            self.assertEqual(save(payload).json, {"result":"OK", "more_tasks_available": True})
        self.assertEqual(save(dict(payload, score=3)).status_code, 409)
        self.assertEqual(json.loads(Path(f"data/{key}/{key}.json").read_text()), payload)
        self.assertIn(b'"score": 2', self.client.get(f"/results/{key}?code=secret").data)
        with sqlite3.connect("database.db") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM results").fetchone(), (1,))

    def test_concurrency_expiry_and_initializer(self):
        dm = self.main.dm
        with ThreadPoolExecutor(8) as pool:
            slots = list(pool.map(lambda i: dm.allocate_task(f"p{i}",f"s{i}"),range(180)))
        self.assertEqual(len(set(slots)),180)
        self.assertIsNone(dm.allocate_task("next","next"))
        self.assertFalse(dm.complete_task(slots[0][0], {}, "different","s0"))
        with sqlite3.connect("database.db") as db:
            db.execute("UPDATE tasks SET time_allocated='2000-01-01' WHERE id=?",(slots[0][0],))
        dm.expire_tasks()
        self.assertEqual(dm.allocate_task("next","next"),slots[0])
        self.assertFalse(dm.complete_task(slots[0][0], {}, "p0","s0"))
        self.assertNotEqual(self.initialize(False).returncode,0)
        Path("database.db").unlink()
        Path("data.csv").write_text("column\nfirst\n")
        self.assertNotEqual(self.initialize(False).returncode,0)
        self.assertFalse(Path("database.db").exists())

    def enter(self, client, url):
        self.assertEqual(client.get(url).status_code, 200)
        return client.post(url, data={"decision": "accept"}, follow_redirects=True)

    def test_no_tasks_code_once_and_original_submission_can_recover_it(self):
        with sqlite3.connect("database.db") as db:
            db.execute("DELETE FROM tasks")
        with patch.dict(os.environ, {"NO_TASKS_COMPLETION_CODE": "FIRST123"}):
            first = self.enter(self.client, self.link())
            self.assertEqual(first.status_code, 200)
            self.assertIn("FIRST123", first.text)
            self.assertIn("Please do not accept any more tasks", first.text)
            self.assertIn("https://app.prolific.co/submissions/complete?cc=FIRST123", first.text)
            self.assertIn("FIRST123", self.client.get(self.link()).text)
            other = self.enter(self.main.app.test_client(), self.link(sid="S2"))
            self.assertEqual(other.status_code, 409)
            self.assertNotIn("FIRST123", other.text)
            self.assertIn("Please return this submission", other.text)
            different_participant = self.enter(self.main.app.test_client(), self.link("P2", "S3"))
            self.assertEqual(different_participant.status_code, 200)
        # Persistence is independent of cookies and of a later code setting.
        with patch.dict(os.environ, {"NO_TASKS_COMPLETION_CODE": "NEWCODE"}):
            recovered = self.enter(self.main.app.test_client(), self.link())
            self.assertIn("FIRST123", recovered.text)
            self.assertNotIn("NEWCODE", recovered.text)
        with sqlite3.connect("database.db") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM no_tasks_completions").fetchone(), (2,))
            self.assertEqual(db.execute("SELECT count(*) FROM results").fetchone(), (0,))
            db.execute("INSERT INTO tasks(id,task_number,status) VALUES ('new-item',1,'waiting')")
        self.assertIn("FIRST123", self.client.get(self.link()).text)
        with sqlite3.connect("database.db") as db:
            self.assertEqual(db.execute("SELECT status FROM tasks").fetchone(), ("waiting",))

    def test_missing_code_does_not_consume_first_claim(self):
        with sqlite3.connect("database.db") as db:
            db.execute("DELETE FROM tasks")
        self.assertEqual(self.enter(self.client, self.link()).status_code, 409)
        with patch.dict(os.environ, {"NO_TASKS_COMPLETION_CODE": "FIRST123"}):
            self.assertIn("FIRST123", self.client.get(self.link()).text)

    def test_no_tasks_receipt_failure_is_retryable(self):
        with sqlite3.connect("database.db") as db:
            db.execute("DELETE FROM tasks")
        with patch.dict(os.environ, {"NO_TASKS_COMPLETION_CODE": "FIRST123",
                                    "NO_TASKS_RECEIPTS_DB": "missing/path.db"}):
            self.assertEqual(self.enter(self.client, self.link()).status_code, 503)
        with patch.dict(os.environ, {"NO_TASKS_COMPLETION_CODE": "FIRST123"}):
            self.assertIn("FIRST123", self.client.get(self.link()).text)

    def test_concurrent_no_tasks_claims_and_shared_batch_receipts(self):
        dm = self.main.dm
        shared = str(Path("shared-receipts.db").resolve())
        def claim(i):
            return dm.claim_no_tasks_completion("P1", f"S{i}", f"batch{i}", "FIRST123", shared)
        with ThreadPoolExecutor(8) as pool:
            codes = list(pool.map(claim, range(12)))
        self.assertEqual(codes.count("FIRST123"), 1)
        winner = codes.index("FIRST123")
        self.assertEqual(claim(winner), "FIRST123")
        self.assertIsNone(dm.claim_no_tasks_completion("P1", f"S{winner}", "another-study", "OTHER", shared))
        self.assertEqual(dm.claim_no_tasks_completion("P2", "S1", "another-study", "OTHER", shared), "OTHER")

    def test_completion_warning_uses_participant_eligibility_and_survives_retry(self):
        key = self.start()
        with sqlite3.connect("database.db") as db:
            # Other copies remain, but this participant has already seen this item.
            db.execute("DELETE FROM tasks WHERE task_number <> 1")
        payload = dict(task_id=key, prolific_pid="P1", session_id="S1", score=2)
        first = self.client.post("/", json=payload)
        self.assertEqual(first.json, {"result": "OK", "more_tasks_available": False})
        self.assertIn("Please do not accept any more tasks", Path("templates/interface.html").read_text())
        with sqlite3.connect("database.db") as db:
            db.execute("INSERT INTO tasks(id,task_number,status) VALUES ('new-item',2,'waiting')")
        self.assertEqual(self.client.post("/", json=payload).json, first.json)
        self.assertEqual(json.loads(Path(f"data/{key}/{key}.json").read_text()), payload)

    def test_completion_with_more_tasks_and_legacy_retry(self):
        key = self.start()
        payload = dict(task_id=key, prolific_pid="P1", session_id="S1", score=2)
        with sqlite3.connect("database.db") as db:
            # Reproduce a response saved before this patch, using the original format.
            db.execute("INSERT INTO results VALUES (?,?,?)", (key, str(payload), "P1"))
            db.execute("UPDATE tasks SET status='completed' WHERE id=?", (key,))
        first = self.client.post("/", json=payload)
        self.assertEqual(first.json, {"result": "OK", "more_tasks_available": True})
        with sqlite3.connect("database.db") as db:
            db.execute("UPDATE tasks SET status='allocated' WHERE status='waiting'")
        self.assertEqual(self.client.post("/", json=payload).json, first.json)


if __name__ == "__main__":
    unittest.main()
