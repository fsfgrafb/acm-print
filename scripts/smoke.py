"""One critical-path check against a fresh disposable PostgreSQL database. Never prints."""

import io
import os
import uuid

from fastapi.testclient import TestClient
from print_platform.cli import migrate
from print_platform.config import ROOT
from print_platform.main import app
from print_platform.workers.conversion import tick
from pypdf import PdfReader, PdfWriter
from sqlalchemy.engine import make_url

url = make_url(os.environ["PLATFORM_DATABASE_URL"])
if not url.database.endswith("_smoke"):
    raise RuntimeError("Smoke check only accepts a disposable *_smoke database")
path = ROOT / "var/smoke.toml"
path.parent.mkdir(exist_ok=True)
path.write_text(
    (ROOT / "config/platform.example.toml")
    .read_text(encoding="utf-8")
    .replace('root = "var/storage"', 'root = "var/smoke-storage"'),
    encoding="utf-8",
)
os.environ["PLATFORM_CONFIG_FILE"] = str(path)
migrate()
origin = {"Origin": "http://localhost:5173"}
admin, member = TestClient(app, headers=origin), TestClient(app, headers=origin)


def expect(response, status=200):
    assert response.status_code == status, (response.status_code, response.text)
    return response.json()


def sign_in(client, identity):
    user = expect(client.post("/api/auth/login", json={"student_id": identity, "password": identity}))
    client.headers["X-CSRF-Token"] = user["csrf_token"]
    user = expect(
        client.post(
            "/api/auth/change-password", json={"current_password": identity, "new_password": identity}
        )
    )
    client.headers["X-CSRF-Token"] = user["csrf_token"]


assert not expect(admin.get("/api/setup/status"))["initialized"], "Use a fresh *_smoke database"
expect(admin.get("/api/public/branding"))
expect(admin.post("/api/setup", json={"student_id": "0001"}))
expect(admin.post("/api/setup", json={"student_id": "0002"}), 409)
sign_in(admin, "0001")
csv = b"student_id,email,phone\n0002,,\n0002,,\n0003,,\n"
preview = expect(admin.post("/api/admin/import/preview", files={"file": ("members.csv", csv)}))
assert [r["status"] for r in preview["rows"]] == ["new", "skipped", "new"]
key = uuid.uuid4().hex
result = expect(admin.post("/api/admin/import/commit?key=" + key, files={"file": ("members.csv", csv)}))
assert result == {"added": 2, "skipped": 1, "invalid": 0}
assert (
    expect(admin.post("/api/admin/import/commit?key=" + key, files={"file": ("members.csv", csv)})) == result
)
sign_in(member, "0002")
expect(member.get("/api/admin/students"), 403)
writer = PdfWriter()
for _ in range(3):
    writer.add_blank_page(595, 842)
fixture = io.BytesIO()
writer.write(fixture)
document = expect(
    member.post("/api/files", files={"file": ("private.pdf", fixture.getvalue(), "application/pdf")})
)
tick(lambda: None)
assert expect(member.get("/api/files/" + document["id"]))["status"] == "ready"
plan = expect(
    member.post(
        "/api/render-plans", json={"document_id": document["id"], "mode": "custom", "expression": "3,1,3"}
    )
)
tick(lambda: None)
assert expect(member.get("/api/render-plans/" + plan["id"]))["status"] == "ready"
pdf = member.get("/api/render-plans/" + plan["id"] + "/pdf")
assert pdf.status_code == 200 and len(PdfReader(io.BytesIO(pdf.content)).pages) == 3
batch = {"idempotency_key": uuid.uuid4().hex, "items": [{"plan_id": plan["id"], "copies": 2}]}
first = expect(member.post("/api/print-batches", json=batch))
assert expect(member.post("/api/print-batches", json=batch))["batch_id"] == first["batch_id"]
batch["items"][0]["copies"] = 1
expect(member.post("/api/print-batches", json=batch), 409)
task = expect(member.get("/api/queue"))["items"][0]
assert task["total_pages"] == 6 and task["filename"] == "private.pdf" and task["plan_id"] == plan["id"]
assert member.get("/api/render-plans/" + task["plan_id"] + "/pdf").status_code == 200
assert expect(admin.get("/api/queue"))["items"][0]["plan_id"] == plan["id"]
other = TestClient(app, headers=origin)
sign_in(other, "0003")
other_task = expect(other.get("/api/queue"))["items"][0]
assert not other_task["mine"] and "filename" not in other_task and "plan_id" not in other_task
expect(other.get("/api/render-plans/" + plan["id"]), 404)
expect(other.get("/api/render-plans/" + plan["id"] + "/pdf"), 404)
expect(other.get("/api/files/" + document["id"]), 404)
expect(other.post("/api/tasks/" + task["id"] + "/cancel"), 404)
expect(member.post("/api/tasks/" + task["id"] + "/cancel"))
assert expect(member.get("/api/queue"))["items"] == []
assert expect(admin.get("/api/admin/stats"))["items"] == []
print(
    "Critical path OK: setup, sessions, CSV, PDF, preview, idempotency, permissions and cancellation. No physical jobs submitted."
)
