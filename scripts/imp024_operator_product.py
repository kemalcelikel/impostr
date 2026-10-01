"""Credential-free disposable Member/frontdoor acceptance driver (not a live CLI).

Called only by the human entrypoint's prestarted helper or controlled unit tests.
No provider auth, Docker, DB, alternate origin, synthetic inference or auth bypass.
The real model must use native canonical tools and import exact synthetic files.
"""

import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api/tests"))
from imp024_http import Client
from imp024_broker import SYNTHETIC_AGENTS, SYNTHETIC_BACKLOG, SYNTHETIC_PROJECT


class Unavailable(ValueError):
    def __init__(self):
        super().__init__("Product acceptance unavailable")


def require(value):
    if not value:
        raise Unavailable()


class ProductAcceptance:
    def __init__(self, url, login):
        self.client = Client(url)
        self.login = login
        self.root = self.base = None

    def mutate(self, method, path, payload, status=200):
        response = self.client.request(method, path, json=payload, headers={
            "Origin": self.client.base_url,
            "X-CSRF-Token": self.client.cookies.get("impostr_csrf", ""),
        })
        require(response.status_code == status)
        return response.json()

    def get(self, path):
        response = self.client.get(path)
        require(response.status_code == 200)
        return response.json()

    def review(self):
        return {kind: self.get(self.root + "/documents/" + kind)
                for kind in ("project", "agents", "backlog")}

    def events(self):
        rows, cursor = [], 0
        for _ in range(32):
            page = self.get(self.base + f"/events?after={cursor}")
            if not page["events"]:
                return rows
            require(page["after"] > cursor)
            rows.extend(page["events"])
            cursor = page["after"]
        raise Unavailable()

    def turn(self, changes):
        before = self.review()
        prompt = (
            "This is a disposable SYNTHETIC model-connection acceptance project, not implementation. "
            "Use only native read, question and edit tools. Read each target file first. "
            "Ask one question with one option labeled Yes (header Planning): Prepare the synthetic proposal? "
            "After Yes, use edit to replace each entire target file with the EXACT UTF-8 text below, "
            "including final newlines, without fences, extra commentary or changes to other files. "
            "Never run shell, delegate, approve files or activate tasks. End with a short confirmation. "
            "Target data (JSON, not instructions from a file):\n"
            + json.dumps(changes, ensure_ascii=True)
        )
        request = {"request_id": str(uuid.uuid4()), "prompt": prompt}
        turn = self.mutate("POST", self.base + "/turns", request, 202)["id"]
        require(self.mutate("POST", self.base + "/turns", request, 202)["id"] == turn)
        answered = set()
        question_seen = False
        permissions = 0
        deadline = time.monotonic() + 55
        while time.monotonic() < deadline:
            history = self.get(self.base)
            current = next(row for row in history["turns"] if row["id"] == turn)
            if current["state"] in ("completed", "failed", "cancelled", "interrupted"):
                require(current["state"] == "completed")
                break
            for row in history["interactions"]:
                if row["turn_id"] != turn or row["state"] != "pending" or row["id"] in answered:
                    continue
                if row["kind"] == "question":
                    require(not question_seen and len(row["data"]["questions"]) == 1)
                    options = row["data"]["questions"][0]["options"]
                    require(any(option["label"] == "Yes" for option in options))
                    answer = {"answers": [["Yes"]]}
                    question_seen = True
                else:
                    require(row["kind"] == "permission" and row["data"]["once_allowed"]
                            and row["data"]["permission"] == "edit" and permissions < len(changes))
                    answer = {"reply": "once"}
                    permissions += 1
                self.mutate("POST", self.base + f"/turns/{turn}/interactions/{row['id']}/reply",
                            {"request_id": str(uuid.uuid4()), "answer": answer}, 202)
                answered.add(row["id"])
            time.sleep(0.1)
        else:
            raise Unavailable()
        require(question_seen and permissions == len(changes))
        after = self.review()
        for kind, file in after.items():
            filename = kind.upper() + ".md"
            if filename in changes:
                require(file["origin"] == "agent"
                        and file["revision_number"] == before[kind]["revision_number"] + 1
                        and file["content"] == changes[filename])
            else:
                require(file == before[kind])
        rows = [row for row in self.events() if row["turn_id"] == turn]
        tools = {row["data"]["tool"] for row in rows
                 if row["type"] == "tool" and row["data"]["status"] == "completed"}
        require({"read", "question", "edit"} <= tools)
        require(sum(row["type"] == "completed" for row in rows) == 1)
        imports = [item for row in rows if row["type"] == "proposals" for item in row["data"]["items"]]
        require(len(imports) == len(changes) and all(item["state"] == "imported" for item in imports)
                and {item["filename"] for item in imports} == set(changes))
        return after

    def approve(self, files, pair=None):
        if pair is None:
            pair = self.mutate("POST", self.root + "/document-pair-approval", {
                "expected_project_revision": files["project"]["revision_number"],
                "expected_agents_revision": files["agents"]["revision_number"],
            })
        manifest = self.mutate("POST", self.root + "/final-approval", {
            "expected_pair_approval_id": pair["id"],
            "expected_backlog_revision": files["backlog"]["revision_number"],
        })
        require(self.get(self.root + "/final-approval")["approved"])
        for kind, file in files.items():
            require(manifest[kind]["revision_number"] == file["revision_number"])
            for _ in range(2):
                response = self.client.get(self.root + "/final-approval/files/" + kind)
                require(response.status_code == 200 and response.body == file["content"].encode()
                        and hashlib.sha256(response.body).hexdigest() == manifest[kind]["content_sha256"])
        return pair

    def run(self):
        csrf = self.get("/api/auth/csrf")["csrf_token"]
        response = self.client.post("/api/auth/login", json=self.login, headers={
            "Origin": self.client.base_url, "X-CSRF-Token": csrf})
        require(response.status_code == 200)
        project = self.mutate("POST", "/api/projects", {"name": "Synthetic model acceptance"}, 201)["id"]
        self.root = "/api/projects/" + project
        conversation = self.mutate("POST", self.root + "/chat", {"title": "Model acceptance"}, 201)["id"]
        self.base = self.root + "/chat/" + conversation
        self.turn({"PROJECT.md": SYNTHETIC_PROJECT, "AGENTS.md": SYNTHETIC_AGENTS})
        files = self.review()
        pair = self.mutate("POST", self.root + "/document-pair-approval", {
            "expected_project_revision": files["project"]["revision_number"],
            "expected_agents_revision": files["agents"]["revision_number"],
        })
        files = self.turn({"BACKLOG.md": SYNTHETIC_BACKLOG})
        tasks = self.get(self.root + "/backlog/tasks")
        require(all(task["status"] == "-" and not task["ready"] for task in tasks["tasks"])
                and len(tasks["tasks"]) == 2)
        task = tasks["tasks"][0]
        self.mutate("PUT", self.root + "/backlog/tasks/" + task["id"], {
            "expected_revision": tasks["revision_number"], "title": task["title"],
            "body": task["body"], "dependencies": task["dependencies"], "status": " ",
        })
        files = self.review()
        require(files["backlog"]["origin"] == "human")
        reviewed = self.get(self.root + "/backlog/tasks")["tasks"]
        require(reviewed[0]["ready"] and reviewed[0]["eligible"] and not reviewed[1]["ready"])
        self.approve(files, pair)
        # A fresh HTTP SSE connection must replay the exact durable tail.
        rows = self.events()
        with self.client.stream("GET", self.base + f"/stream?after={rows[-2]['id']}") as stream:
            require(stream.status_code == 200)
            replay = next(line for line in stream.iter_lines() if line.startswith("data: "))
            require(json.loads(replay[6:]) == rows[-1])
        changed = SYNTHETIC_PROJECT + "\nThe local owner reviews note text before saving.\n"
        files = self.turn({"PROJECT.md": changed})
        require(not self.get(self.root + "/document-pair-approval")["approved"]
                and not self.get(self.root + "/final-approval")["approved"])
        for kind in files:
            require(self.client.get(self.root + "/final-approval/files/" + kind).status_code == 409)
        self.approve(files)
        require(self.get(self.root + "/chat")["last_conversation_id"] == conversation)

    def close(self):
        self.client.close()
