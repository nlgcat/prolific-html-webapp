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
                                          "PROLIFIC_STUDY_ID": "study1"})
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
            self.assertEqual(save(payload).json, {"result":"OK"})
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


if __name__ == "__main__":
    unittest.main()
