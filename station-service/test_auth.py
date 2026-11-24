"""Account lifecycle and HTTP authorization regression tests."""

import io
import json
import os
import secrets
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import cv2
import numpy as np
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

import app as station_app
import openpose_runner as runner_module
import session_catalog
import session_manager as recorder_module
from auth import config as auth_config, create_admin, db as auth_db, list_users, security
from auth.config import allowed_web_origins
from auth.db import engine_for
from auth.models import AuthSession, Invitation, User, utcnow
from station_cameras import CameraDevice, StationCameraManager, _stable_device_id
from test_station_cameras import FakeCapture, FakeWriter


WEB_ORIGIN = "https://station.example.com"
WEB_HEADERS = {"Origin": WEB_ORIGIN}
API_URL = "https://api.example.com"
ADMIN = "admin@example.com"
RESIDENT_A = "resident-a@example.com"
RESIDENT_B = "resident-b@example.com"


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(24)
        cls.hashed_password = security.password_hasher.hash(cls.password)

    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.sessions = root / "sessions"
        self.sessions.mkdir()
        database_url = f"sqlite:///{(root / 'auth.sqlite3').as_posix()}"
        self.enterContext(patch.dict(os.environ, {"AUTH_DATABASE_URL": database_url, "AUTH_WEB_ORIGIN": WEB_ORIGIN}))
        self.enterContext(patch.object(security, "_login_attempts", {}))
        self.enterContext(patch.object(security, "_login_window_end", 0.0))
        self.engine = engine_for(database_url)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(engine_for.cache_clear)
        command.upgrade(Config(str(Path(__file__).parent / "alembic.ini")), "head")
        with Session(self.engine, expire_on_commit=False) as db:
            users = [User(email=email, password_hash=self.hashed_password, role=role) for email, role in (
                (ADMIN, "admin"), (RESIDENT_A, "resident"), (RESIDENT_B, "resident"),
            )]
            db.add_all(users)
            db.commit()
            self.ids = {user.email: user.id for user in users}

        self.enterContext(patch.object(runner_module, "SESSIONS_DIR", self.sessions))
        self.enterContext(patch.object(session_catalog, "SESSIONS_DIR", self.sessions))
        self.enterContext(patch.object(recorder_module, "SESSIONS_DIR", self.sessions))
        self.recordings = recorder_module.SessionManager()
        self.enterContext(patch.object(station_app, "session_manager", self.recordings))
        self.addCleanup(self.recordings.shutdown)

    def client(self, email=None, *, browser=True):
        client = TestClient(station_app.app, base_url=API_URL, headers=WEB_HEADERS if browser else {})
        self.addCleanup(client.close)
        if email is not None:
            response = self.login(client, email)
            self.assertEqual(response.status_code, 204, response.text)
        return client

    def login(self, client, email=RESIDENT_A, password=None):
        return client.post("/auth/login", json={"email": email, "password": password or self.password})

    def saved_session(self, session_id, owner=None, *, video=False):
        directory = self.sessions / session_id
        raw = directory / "raw"
        output = directory / "analysis" / "side"
        raw.mkdir(parents=True)
        (output / "plots").mkdir(parents=True)
        metadata = {"session_label": session_id, "duration_seconds": 0.1, "resident_or_study_id": RESIDENT_A}
        if owner is not None:
            metadata["owner_user_id"] = self.ids[owner]
        (directory / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        (output / "posture_metrics.csv").write_text(
            "frame,Time_seconds,Neck_Flexion_Extension,Neck_RULA_Category\n0,0,4,flexion_0_10\n", encoding="utf-8",
        )
        image = np.zeros((48, 64, 3), dtype=np.uint8)
        (output / "plots" / "neck.png").write_bytes(cv2.imencode(".png", image)[1].tobytes())
        if video:
            writer = cv2.VideoWriter(str(raw / "side.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
            try:
                self.assertTrue(writer.isOpened())
                writer.write(image)
            finally:
                writer.release()

    def invitation(self, email="invited@example.com"):
        response = self.client(ADMIN).post("/admin/invitations", json={"email": email})
        self.assertEqual(response.status_code, 201, response.text)
        invitation = response.json()
        link = urlsplit(invitation["invitation_url"])
        self.assertEqual(link.path, "/accept-invitation")
        self.assertEqual(link.query, "")
        self.assertEqual(f"{link.scheme}://{link.netloc}", WEB_ORIGIN)
        return parse_qs(link.fragment)["token"][0]

    def acceptance(self, token, email="invited@example.com"):
        return {"token": token, "email": email, "password": self.password}

    def test_login_uses_normalized_email_and_secure_cookie(self):
        client = self.client()
        response = self.login(client, " RESIDENT-A@Example.com ")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        cookie = response.headers["set-cookie"].lower()
        for flag in ("__host-station_session=", "httponly", "secure", "samesite=strict", "path=/"):
            self.assertIn(flag, cookie)
        identity = client.get("/auth/me")
        self.assertEqual(identity.json(), {"id": self.ids[RESIDENT_A], "email": RESIDENT_A, "role": "resident"})
        self.assertEqual(identity.headers["cache-control"], "no-store")
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(AuthSession.token_hash)), security.token_hash(client.cookies["__Host-station_session"]))

    def test_invalid_password_and_unknown_email_return_same_error(self):
        client = self.client()
        wrong = self.login(client, password=secrets.token_urlsafe(24))
        unknown = self.login(client, "unknown@example.com")
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(wrong.json(), unknown.json())
        self.assertEqual(wrong.json(), {"detail": "Invalid email or password."})

    def test_password_persistence_is_one_way_and_payload_errors_hide_input(self):
        with Session(self.engine) as db:
            user = db.get(User, self.ids[RESIDENT_A])
            self.assertTrue(user.password_hash.startswith("$argon2id$"))
            self.assertNotEqual(user.password_hash, self.password)
            self.assertTrue(security.password_hasher.verify(self.password, user.password_hash))
        invalid_password = self.password * 10
        error = self.login(self.client(), password=invalid_password)
        self.assertEqual(error.status_code, 422)
        self.assertNotIn(invalid_password, error.text)

    def test_browser_logout_revokes_session_and_rejects_untrusted_origins(self):
        client = self.client(RESIDENT_A)
        cookie = client.cookies["__Host-station_session"]
        rejected = client.post("/auth/logout", headers={"Origin": "https://other.example.com"})
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(client.get("/auth/me").status_code, 200)
        self.assertEqual(client.post("/auth/logout").status_code, 204)
        self.assertEqual(client.get("/auth/me", headers={"Cookie": f"__Host-station_session={cookie}"}).status_code, 401)
        self.assertEqual(self.login(self.client(browser=False)).status_code, 403)

    def test_local_browser_aliases_use_only_the_configured_port(self):
        local = {"AUTH_WEB_ORIGIN": "http://127.0.0.1:5173", "AUTH_ALLOW_INSECURE_LOCAL_HTTP": "1"}
        with patch.dict(os.environ, local):
            self.assertEqual(allowed_web_origins(), [
                "http://127.0.0.1:5173", "http://localhost:5173", "http://[::1]:5173",
            ])
            client = self.client()
            credentials = {"email": RESIDENT_A, "password": self.password}
            good = client.post("/auth/login", json=credentials, headers={"Origin": "http://localhost:5173"})
            wrong_port = client.post("/auth/login", json=credentials, headers={"Origin": "http://localhost:5174"})
            self.assertEqual(good.status_code, 204)
            self.assertEqual(wrong_port.status_code, 403)
            with patch.dict(os.environ, {"AUTH_ALLOW_INSECURE_LOCAL_HTTP": "0"}):
                self.assertEqual(allowed_web_origins(), [local["AUTH_WEB_ORIGIN"]])
            with patch.dict(os.environ, {"AUTH_WEB_ORIGIN": WEB_ORIGIN}):
                self.assertEqual(allowed_web_origins(), [WEB_ORIGIN])

    def test_expired_or_inactive_session_is_rejected(self):
        client = self.client(RESIDENT_A)
        with Session(self.engine) as db:
            db.execute(update(AuthSession).values(expires_at=utcnow() - timedelta(seconds=1)))
            db.commit()
        self.assertEqual(client.get("/auth/me").status_code, 401)
        self.login(client)
        with Session(self.engine) as db:
            db.execute(update(User).where(User.id == self.ids[RESIDENT_A]).values(is_active=False))
            db.commit()
        self.assertEqual(client.get("/auth/me").status_code, 401)
        self.assertEqual(self.login(client).status_code, 401)

    def test_login_attempt_limit_applies_to_both_credential_endpoints(self):
        with patch.object(security, "_login_window_end", time.monotonic() + 60):
            security._login_attempts["testclient"] = 12
            browser = self.login(self.client())
            native = self.client(browser=False).post("/auth/token", json={"email": RESIDENT_A, "password": self.password})
        for response in (browser, native):
            self.assertEqual(response.status_code, 429)
            self.assertIn("retry-after", response.headers)

    def test_resident_lists_only_owned_sessions_and_admin_identifies_owners(self):
        self.saved_session("session-a", RESIDENT_A)
        self.saved_session("session-b", RESIDENT_B)
        self.saved_session("legacy")
        sessions = self.client(RESIDENT_A).get("/sessions").json()["sessions"]
        self.assertEqual([item["session_id"] for item in sessions], ["session-a"])
        self.assertNotIn("owner_email", sessions[0])
        admin = self.client(ADMIN)
        data = {item["session_id"]: item for item in admin.get("/sessions").json()["sessions"]}
        self.assertEqual(set(data), {"session-a", "session-b", "legacy"})
        self.assertEqual(data["session-a"]["owner_email"], RESIDENT_A)
        self.assertEqual(data["session-b"]["owner_user_id"], self.ids[RESIDENT_B])
        self.assertIsNone(data["legacy"]["owner_email"])
        for session in data:
            self.assertEqual(admin.get(f"/sessions/{session}").status_code, 200)

    def test_ownership_protects_detail_status_metrics_frames_plots_and_retries(self):
        self.saved_session("session-a", RESIDENT_A, video=True)
        self.saved_session("session-b", RESIDENT_B, video=True)
        self.saved_session("legacy", video=True)
        resident = self.client(RESIDENT_A)
        read_paths = (
            "", "/analysis-status", "/analysis/metrics/neck_flexion_extension",
            "/analysis/frame?view=side&frame=0", "/analysis/side/plots/neck.png",
        )
        for path in read_paths:
            with self.subTest(path=path):
                self.assertEqual(resident.get(f"/sessions/session-a{path}").status_code, 200)
                foreign = resident.get(f"/sessions/session-b{path}")
                self.assertEqual(foreign.status_code, 404)
                self.assertEqual(foreign.json(), {"detail": "Session not found."})
                self.assertEqual(resident.get(f"/sessions/legacy{path}").status_code, 404)
        with patch.object(runner_module.openpose_runner, "retry_posture", return_value={"status": "processing"}) as retry, \
             patch.object(runner_module.openpose_runner, "start", return_value={"status": "processing"}) as analyze:
            self.assertEqual(resident.post("/sessions/session-b/analysis/side/retry").status_code, 404)
            self.assertEqual(resident.post("/sessions/session-b/analyze").status_code, 404)
            retry.assert_not_called()
            analyze.assert_not_called()
            self.assertEqual(resident.post("/sessions/session-a/analysis/side/retry").status_code, 200)
            self.assertEqual(resident.post("/sessions/session-a/analyze").status_code, 200)

    def test_recording_and_session_endpoints_require_authentication(self):
        client = self.client()
        endpoints = (
            ("GET", "/sessions"), ("GET", "/sessions/current"), ("GET", "/sessions/saved"),
            ("GET", "/sessions/saved/analysis-status"),
            ("GET", "/sessions/saved/analysis/metrics/neck_flexion_extension"),
            ("GET", "/sessions/saved/analysis/frame?view=side&frame=0"),
            ("GET", "/sessions/saved/analysis/side/plots/neck.png"),
            ("POST", "/sessions/saved/analysis/side/retry"), ("POST", "/sessions/saved/analyze"),
            ("POST", "/sessions/start"), ("POST", "/sessions/stop"), ("GET", "/cameras"),
        )
        for method, path in endpoints:
            with self.subTest(path=path):
                self.assertEqual(client.request(method, path, json={"session_label": "sample"} if path == "/sessions/start" else None).status_code, 401)
        self.assertEqual(client.post("/auth/signup", json={"email": "new@example.com"}).status_code, 404)

    def test_native_token_supports_history_and_revocation_without_station_controls(self):
        resident = self.client(browser=False)
        self.saved_session("session-a", RESIDENT_A, video=True)
        self.saved_session("session-b", RESIDENT_B)
        credentials = {"email": RESIDENT_A, "password": self.password}
        self.assertEqual(self.client().post("/auth/token", json=credentials).status_code, 403)
        issued = resident.post("/auth/token", json=credentials)
        self.assertEqual(issued.status_code, 200)
        token = issued.json()
        self.assertNotIn("set-cookie", issued.headers)
        self.assertEqual(token["expires_in"], security.NATIVE_SECONDS)
        self.assertEqual(token["token_type"], "bearer")
        resident.headers["Authorization"] = f"Bearer {token['access_token']}"
        self.assertEqual(resident.get("/auth/me").json()["id"], self.ids[RESIDENT_A])
        self.assertEqual([item["session_id"] for item in resident.get("/sessions").json()["sessions"]], ["session-a"])
        self.assertIs(resident.get("/sessions/session-a").json()["review_media_available"], False)
        self.assertIs(self.client(RESIDENT_A).get("/sessions/session-a").json()["review_media_available"], True)
        self.assertEqual(resident.get("/sessions/session-a/analysis/metrics/neck_flexion_extension").status_code, 200)
        self.assertEqual(resident.get("/sessions/session-b").status_code, 404)
        self.assertEqual(resident.get("/sessions/session-a/analysis/frame?view=side&frame=0").status_code, 403)
        self.assertEqual(resident.get("/cameras").status_code, 403)
        self.assertEqual(resident.post("/sessions/start", json={"session_label": "test"}).status_code, 403)
        self.assertEqual(resident.post("/auth/logout").status_code, 204)
        self.assertEqual(resident.get("/sessions").status_code, 401)

    def test_only_admin_can_invite_and_invited_resident_can_activate_once(self):
        email = "invited@example.com"
        for client, code in ((self.client(), 401), (self.client(RESIDENT_A), 403)):
            self.assertEqual(client.post("/admin/invitations", json={"email": email}).status_code, code)
        token = self.invitation(email.upper())
        with Session(self.engine) as db:
            invitation = db.scalar(select(Invitation))
            self.assertEqual(invitation.email, email)
            self.assertEqual(invitation.token_hash, security.token_hash(token))
            self.assertEqual(invitation.invited_by_user_id, self.ids[ADMIN])
        invitee = self.client()
        self.assertEqual(invitee.post("/auth/invitations/preview", json={"token": token}).json(), {"email": email})
        self.assertEqual(invitee.post("/auth/invitations/accept", json=self.acceptance(token, "wrong@example.com")).status_code, 400)
        accepted = invitee.post("/auth/invitations/accept", json=self.acceptance(token))
        self.assertEqual(accepted.status_code, 201, accepted.text)
        self.assertEqual(accepted.json()["role"], "resident")
        self.assertEqual(invitee.post("/auth/invitations/accept", json=self.acceptance(token)).status_code, 400)
        self.assertEqual(invitee.post("/auth/invitations/preview", json={"token": token}).status_code, 400)
        self.assertEqual(self.login(invitee, email).status_code, 204)

    def test_expired_and_invalid_invitations_fail_and_expired_link_can_be_replaced(self):
        token = self.invitation()
        with Session(self.engine) as db:
            db.execute(update(Invitation).values(expires_at=utcnow() - timedelta(minutes=1)))
            db.commit()
        invitee = self.client()
        self.assertEqual(invitee.post("/auth/invitations/accept", json=self.acceptance(token)).status_code, 400)
        self.assertEqual(invitee.post("/auth/invitations/accept", json=self.acceptance(security.new_token())).status_code, 400)
        replacement = self.invitation()
        self.assertNotEqual(token, replacement)
        self.assertEqual(invitee.post("/auth/invitations/accept", json=self.acceptance(token)).status_code, 400)
        self.assertEqual(invitee.post("/auth/invitations/accept", json=self.acceptance(replacement)).status_code, 201)

    def test_duplicate_account_invitation_and_acceptance_fail(self):
        admin = self.client(ADMIN)
        self.assertEqual(admin.post("/admin/invitations", json={"email": RESIDENT_A.upper()}).status_code, 409)
        token = self.invitation()
        self.assertEqual(admin.post("/admin/invitations", json={"email": "invited@example.com"}).status_code, 409)
        with Session(self.engine) as db:
            db.add(User(email="invited@example.com", role="resident", password_hash=self.hashed_password))
            db.commit()
        duplicate = self.client().post("/auth/invitations/accept", json=self.acceptance(token))
        self.assertEqual(duplicate.status_code, 409)

    def test_invited_inactive_resident_keeps_stable_id_and_old_sessions_are_revoked(self):
        old_client = self.client(RESIDENT_A)
        with Session(self.engine) as db:
            db.execute(update(User).where(User.id == self.ids[RESIDENT_A]).values(is_active=False))
            db.commit()
        token = self.invitation(RESIDENT_A)
        new_client = self.client()
        accepted = new_client.post("/auth/invitations/accept", json=self.acceptance(token, RESIDENT_A))
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(accepted.json()["id"], self.ids[RESIDENT_A])
        self.assertEqual(old_client.get("/auth/me").status_code, 401)
        self.assertEqual(self.login(new_client).status_code, 204)

    def test_concurrent_acceptance_only_creates_one_account(self):
        payload = self.acceptance(self.invitation())
        clients = [self.client(), self.client()]
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda client: client.post("/auth/invitations/accept", json=payload).status_code, clients))
        self.assertEqual(sorted(statuses), [201, 400])

    def test_recording_metadata_owner_comes_from_login_and_active_controls_enforce_it(self):
        resident = self.client(RESIDENT_A)
        other = self.client(RESIDENT_B)
        self.assertEqual(resident.post("/sessions/start", json={"session_label": "test", "owner_user_id": self.ids[RESIDENT_B]}).status_code, 422)
        device = CameraDevice(_stable_device_id("auth-test-camera"), "Auth test camera", 0)
        config = {"side_camera_id": device.id, "rear_camera_id": None}
        with patch("station_cameras.load_config", return_value=config):
            camera_manager = StationCameraManager(enumerate_devices=lambda: [device], capture_factory=lambda _: FakeCapture())
        camera_manager.start()
        self.addCleanup(camera_manager.shutdown)
        self.assertIsNotNone(camera_manager.stream_for(device.id).wait_for_frame(timeout=1))
        with patch.object(recorder_module, "station_camera_manager", camera_manager), \
             patch.object(recorder_module.cv2, "VideoWriter", side_effect=lambda *args: FakeWriter()), \
             patch.object(runner_module.openpose_runner, "start", return_value={"status": "processing"}):
            started = resident.post("/sessions/start", json={"session_label": "ownership test"})
            self.assertEqual(started.status_code, 200, started.text)
            session_id = started.json()["session_id"]
            metadata = self.sessions / session_id / "metadata.json"
            self.assertEqual(json.loads(metadata.read_text(encoding="utf-8"))["owner_user_id"], self.ids[RESIDENT_A])
            self.assertEqual(other.get("/sessions/current").json(), {"status": "idle"})
            self.assertEqual(other.post("/sessions/stop").status_code, 404)
            self.assertEqual(resident.get("/sessions/current").json()["session_id"], session_id)
            stopped = resident.post("/sessions/stop")
            self.assertEqual(stopped.status_code, 200, stopped.text)
            self.assertEqual(stopped.json()["metadata"]["owner_user_id"], self.ids[RESIDENT_A])

    def test_first_admin_bootstrap_hashes_password_and_prevents_repeating(self):
        with Session(self.engine) as db:
            db.execute(delete(User).where(User.role == "admin"))
            db.commit()
        with patch("builtins.input", return_value="FIRST-ADMIN@example.com"), \
             patch.object(create_admin, "getpass", return_value=self.password), patch("builtins.print"):
            create_admin.main()
        with Session(self.engine) as db:
            user = db.scalar(select(User).where(User.role == "admin"))
            self.assertEqual(user.email, "first-admin@example.com")
            self.assertTrue(security.password_hasher.verify(self.password, user.password_hash))
        with self.assertRaisesRegex(SystemExit, "already exists"):
            create_admin.main()

    def test_cli_admin_logs_in_through_the_api_database(self):
        with Session(self.engine) as db:
            db.execute(delete(User).where(User.role == "admin"))
            db.commit()
        with patch("builtins.input", return_value="lab-admin@example.com"), \
             patch.object(create_admin, "getpass", return_value=self.password), patch("builtins.print"):
            create_admin.main()
        client = self.client()
        self.assertEqual(self.login(client, "lab-admin@example.com").status_code, 204)
        self.assertEqual(client.get("/auth/me").json()["role"], "admin")
        wrong = self.login(self.client(), "lab-admin@example.com", secrets.token_urlsafe(24))
        self.assertEqual((wrong.status_code, wrong.json()), (401, {"detail": "Invalid email or password."}))

    def test_create_admin_refuses_existing_email_without_duplicating(self):
        with Session(self.engine) as db:
            db.execute(delete(User).where(User.role == "admin"))
            db.commit()
        with patch("builtins.input", return_value=RESIDENT_A.upper()), \
             patch.object(create_admin, "getpass") as password_prompt, patch("builtins.print"), \
             self.assertRaisesRegex(SystemExit, "already exists"):
            create_admin.main()
        password_prompt.assert_not_called()
        with Session(self.engine) as db:
            self.assertEqual(db.scalars(select(User.role).where(User.email == RESIDENT_A)).all(), ["resident"])

    def test_create_admin_reports_unmigrated_database_without_creating_it(self):
        missing = self.sessions.parent / "missing.sqlite3"
        with patch.dict(os.environ, {"AUTH_DATABASE_URL": f"sqlite:///{missing.as_posix()}"}), \
             patch("builtins.print"), self.assertRaisesRegex(SystemExit, "alembic upgrade head"):
            create_admin.main()
        self.assertFalse(missing.exists())

    def test_list_users_prints_only_safe_fields(self):
        token = self.invitation()
        cookie = self.client(ADMIN).cookies.get("__Host-station_session")
        with Session(self.engine) as db:
            db.execute(update(User).where(User.email == RESIDENT_B).values(is_active=False))
            db.commit()
        output = io.StringIO()
        with redirect_stdout(output):
            list_users.main()
        text = output.getvalue()
        for email in (ADMIN, RESIDENT_A, RESIDENT_B):
            self.assertIn(email, text)
        self.assertRegex(text, rf"{RESIDENT_B}\s+resident\s+inactive")
        self.assertRegex(text, rf"{ADMIN}\s+admin\s+active")
        for secret in (self.hashed_password, "$argon2", token, security.token_hash(token), cookie):
            self.assertNotIn(secret, text)


class DatabaseConfigTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ))
        os.environ.pop("AUTH_DATABASE_URL", None)
        self.addCleanup(os.chdir, os.getcwd())

    def test_default_sqlite_path_ignores_working_directory(self):
        expected = f"sqlite:///{(Path(__file__).resolve().parent / 'auth.sqlite3').as_posix()}"
        for directory in (tempfile.gettempdir(), Path(__file__).resolve().parents[1], Path(__file__).parent):
            os.chdir(directory)
            self.assertEqual(auth_config.database_url(), expected)
        os.environ["AUTH_DATABASE_URL"] = "   "
        self.assertEqual(auth_config.database_url(), expected)

    def test_relative_sqlite_override_resolves_against_service_directory(self):
        os.environ["AUTH_DATABASE_URL"] = "sqlite:///dev/other.sqlite3"
        expected = (Path(__file__).resolve().parent / "dev" / "other.sqlite3").as_posix()
        for directory in (tempfile.gettempdir(), Path(__file__).parent):
            os.chdir(directory)
            self.assertEqual(auth_config.database_url(), f"sqlite:///{expected}")

    def test_database_url_variable_overrides_default_for_every_consumer(self):
        with tempfile.TemporaryDirectory() as root:
            url = f"sqlite:///{(Path(root) / 'override.sqlite3').as_posix()}"
            os.environ["AUTH_DATABASE_URL"] = url
            self.addCleanup(engine_for.cache_clear)
            self.assertEqual(auth_config.database_url(), url)
            self.assertEqual(str(auth_db.engine().url), url)
            self.assertIs(auth_db.engine(), engine_for(url))
            auth_db.engine().dispose()

        os.environ["AUTH_DATABASE_URL"] = "postgresql+psycopg://station:s3cret@db.example.com:5432/identity"
        self.assertEqual(auth_config.database_url(), os.environ["AUTH_DATABASE_URL"])
        self.assertIsNone(auth_config.sqlite_path())
        self.assertNotIn("s3cret", auth_config.database_description())
