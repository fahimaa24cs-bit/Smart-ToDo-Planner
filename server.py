"""Smart To-Do Planner v3 backend.

This version intentionally uses only Python's standard library so it can be run
straight from PyCharm without installing Flask or other server packages.
"""
import base64
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

BASE = Path(__file__).resolve().parent
PORT = int(os.getenv("PORT", "8000"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna").strip() or "gpt-6-luna"


def load_dotenv(path=BASE / ".env"):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
MODEL = os.getenv("OPENAI_MODEL", MODEL).strip() or MODEL
sessions = {}
sessions_lock = threading.Lock()

SYSTEM = """
You are Smart To-Do Planner, a practical and friendly productivity assistant for a college student.
Understand the user's intent before deciding whether to create tasks.

IMPORTANT BEHAVIOR:
- Answer normal questions naturally. Do NOT turn every sentence into a task.
- If the user asks for advice, prioritization, an explanation, or general conversation, return a useful natural answer and an empty tasks array.
- If the user asks to plan a day/week, give a realistic schedule. Create task suggestions only when they are actionable and useful.
- If the user asks to break a project or goal into steps, create clear, actionable suggested tasks.
- If the user asks to create/add tasks, create tasks.
- Never treat words such as "tomorrow", "today", "help me", "what should I do", or "can you" as task titles by themselves.
- Use the user's existing tasks and spaces as context, but do not invent existing tasks.
- For task suggestions, use only spaces supplied by the app. Use the matching space emoji.
- Keep suggested task titles concise and actionable.
- Priority must be one of: high, medium, low.
- If the user asks for a table, return a table string in addition to any useful reply.

Return ONLY valid JSON with this exact top-level shape:
{
  "reply": "natural helpful answer",
  "tasks": [
    {"title":"...","space":"College","minutes":30,"emoji":"🎓","priority":"high"}
  ],
  "table": "optional plain-text table or empty string"
}
""".strip()

TASK_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "reply": {"type": "string"},
        "tasks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "title": {"type": "string"}, "space": {"type": "string"},
                "minutes": {"type": "integer"}, "emoji": {"type": "string"},
                "priority": {"type": "string", "enum": ["high", "medium", "low"]}
            },
            "required": ["title", "space", "minutes", "emoji", "priority"]
        }},
        "table": {"type": "string"}
    },
    "required": ["reply", "tasks", "table"]
}

IMAGE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"tasks": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "title": {"type": "string"}, "space": {"type": "string"},
            "minutes": {"type": "integer"}, "emoji": {"type": "string"},
            "priority": {"type": "string", "enum": ["high", "medium", "low"]}
        },
        "required": ["title", "space", "minutes", "emoji", "priority"]
    }}},
    "required": ["tasks"]
}


def clean_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        parts = text.split("\n", 1)
        text = parts[1] if len(parts) == 2 else text
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text.strip())


def output_text(response):
    if response.get("output_text"):
        return response["output_text"]
    chunks = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks)


def openai_request(payload):
    if not API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {e.code}: {detail[:600]}") from e


def safe_space_emoji(space_data, name):
    for s in space_data:
        if s.get("name") == name:
            return s.get("emoji") or "📝"
    return "📝"


def fallback(message, context):
    lower = message.lower()
    spaces = context.get("spaces") or ["Personal"]
    space_data = context.get("space_data") or []
    college = "College" if "College" in spaces else spaces[0]
    projects = "Projects" if "Projects" in spaces else spaces[0]
    if any(x in lower for x in ["help me plan tomorrow", "plan tomorrow", "tomorrow"]):
        active = context.get("tasks") or []
        n = len(active)
        return {"reply": f"Sure. For tomorrow, start with your highest-priority work, then move to the next important task, and keep lighter work for later. You currently have {n} active task{'s' if n != 1 else ''}. If you tell me your available hours, I can make the plan more specific.", "tasks": [], "table": ""}
    if any(x in lower for x in ["what should i do first", "dbms", "python", "study", "priorit"]):
        return {"reply": "I would start with the most urgent or high-impact academic work, then use shorter sessions for practice and revision.", "tasks": [
            {"title": "Review the main concepts", "space": college, "minutes": 35, "emoji": safe_space_emoji(space_data, college), "priority": "high"},
            {"title": "Practice questions", "space": college, "minutes": 45, "emoji": "📝", "priority": "medium"},
            {"title": "Review mistakes and weak areas", "space": college, "minutes": 30, "emoji": "🔎", "priority": "medium"},
            {"title": "Do a short final revision", "space": college, "minutes": 20, "emoji": "🔁", "priority": "medium"}], "table": ""}
    if any(x in lower for x in ["project", "app", "website"]):
        return {"reply": "I can break the project into practical stages such as requirements, implementation, testing, and polish. Tell me the project goal and I can make the steps specific.", "tasks": [
            {"title": "Define requirements and user flow", "space": projects, "minutes": 30, "emoji": safe_space_emoji(space_data, projects), "priority": "high"},
            {"title": "Build the core feature", "space": projects, "minutes": 90, "emoji": safe_space_emoji(space_data, projects), "priority": "high"},
            {"title": "Test and polish", "space": projects, "minutes": 45, "emoji": "🧪", "priority": "medium"}], "table": ""}
    return {"reply": "I can help with planning, prioritization, explanations, schedules, or turning a clear plan into tasks. Tell me what you are trying to accomplish and I will work through it with you.", "tasks": [], "table": ""}


def assistant_result(message, session_id, context):
    if not API_KEY:
        return fallback(message, context)
    with sessions_lock:
        history = sessions.setdefault(session_id, [])[-12:]
    user_context = f"User spaces: {context.get('spaces', [])}. Current active tasks: {context.get('tasks', [])}. Space metadata: {context.get('space_data', [])}."
    inputs = [{"role": "system", "content": SYSTEM}]
    inputs.extend(history)
    inputs.append({"role": "user", "content": f"{user_context}\n\nUser request: {message}"})
    response = openai_request({
        "model": MODEL,
        "input": inputs,
        "text": {"format": {"type": "json_schema", "name": "smart_todo_response", "strict": True, "schema": TASK_SCHEMA}},
    })
    result = clean_json(output_text(response))
    result.setdefault("reply", "")
    result.setdefault("tasks", [])
    result.setdefault("table", "")
    allowed = {s.get("name") for s in context.get("space_data", [])}
    for t in result["tasks"]:
        if allowed and t.get("space") not in allowed:
            t["space"] = next(iter(allowed))
        t["emoji"] = safe_space_emoji(context.get("space_data", []), t.get("space"))
        t["minutes"] = max(1, int(t.get("minutes") or 30))
    with sessions_lock:
        sessions.setdefault(session_id, []).extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": result.get("reply", "")},
        ])
    return result


class Handler(SimpleHTTPRequestHandler):
    def _json(self, code, data):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self._json(200, {"ok": True, "ai": bool(API_KEY), "model": MODEL, "backend": "standard-library"})
            return
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if path == "/api/assistant":
            try:
                data = json.loads(raw.decode("utf-8"))
                message = str(data.get("message", "")).strip()
                if not message:
                    self._json(400, {"error": "Message is required."})
                    return
                context = data.get("context") or {}
                session_id = str(data.get("session_id") or uuid4())
                self._json(200, assistant_result(message, session_id, context))
            except Exception as exc:
                self._json(502, {"error": str(exc)})
            return
        if path == "/api/image-tasks":
            # Browser sends multipart/form-data. Parse it with the standard library.
            try:
                import cgi
                env = {"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", ""), "CONTENT_LENGTH": str(length)}
                form = cgi.FieldStorage(fp=io_bytes(raw), environ=env, keep_blank_values=True)
                item = form["image"] if "image" in form else None
                if item is None:
                    self._json(400, {"error": "Image is required."})
                    return
                image = item.file.read()
                mime = item.type or "image/png"
                if not API_KEY:
                    self._json(503, {"error": "Live AI is not configured."})
                    return
                data_url = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
                prompt = """
Analyze this image as a task-list extractor. Return ONLY JSON.
Read the visible task items exactly as written. Do not invent, merge, paraphrase, or duplicate tasks.
Ignore decorative text, titles, motivational text, emojis used only for decoration, page headings, and UI labels.
If a checklist contains four actual task rows, return exactly four tasks.
Use Personal unless a task's space is clearly indicated.
Schema: {"tasks":[{"title":"...","space":"Personal","minutes":30,"emoji":"📝","priority":"medium"}]}
""".strip()
                response = openai_request({
                    "model": MODEL,
                    "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": data_url}]}],
                    "text": {"format": {"type": "json_schema", "name": "image_task_response", "strict": True, "schema": IMAGE_SCHEMA}},
                })
                result = clean_json(output_text(response))
                self._json(200, result)
            except Exception as exc:
                self._json(502, {"error": f"Image analysis failed: {exc}"})
            return
        self._json(404, {"error": "Not found"})

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")


class io_bytes:
    """Tiny file-like wrapper used by cgi.FieldStorage."""
    def __init__(self, data):
        from io import BytesIO
        self._io = BytesIO(data)
    def read(self, *args):
        return self._io.read(*args)
    def readline(self, *args):
        return self._io.readline(*args)


def main():
    print("=" * 56)
    print("Smart To-Do Planner v3")
    print(f"Server: http://127.0.0.1:{PORT}")
    print("Backend: Python standard library (no Flask required)")
    print(f"Live AI: {'ON' if API_KEY else 'OFF'}")
    if API_KEY:
        print(f"Model: {MODEL}")
    else:
        print("Live AI is OFF. Copy .env.example to .env and add OPENAI_API_KEY for full AI reasoning.")
    print("Press Ctrl+C to stop the server.")
    print("=" * 56)
    os.chdir(BASE)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
