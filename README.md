# Smart To-Do Planner v3

A visual productivity planner with manual tasks, spaces, focus sessions, table conversion, image task extraction, and a real AI assistant through a Python backend.

## Main corrections in v3

- Important star turns yellow when selected and remains yellow after saving.
- Space controls the task emoji automatically; there is no manual emoji selector.
- Focus Stop resets the timer to the original duration.
- Focus Complete shows `completed` and resets the next session.
- Complete button has its own spacing below Start/Pause/Stop.
- Tasks → Table requires the user to provide tasks before generating a table.
- Image → Tasks filters decorative text and can use the live AI vision endpoint for exact task extraction.
- Smart Assistant distinguishes normal questions from task-creation requests.
- `server.py` is the direct PyCharm entry point; `start_server.py` is also available.
- No API key is stored in frontend JavaScript.

## Open the UI only

Double-click `index.html`.

## Run the full AI version in PyCharm

1. Open the project folder in PyCharm.
2. Configure a Python interpreter: **Settings → Project → Python Interpreter**.
3. Open the PyCharm Terminal and run once:

```bash
python -m pip install -r requirements.txt
```

4. Copy `.env.example` to `.env`.
5. Put your API key in `.env`:

```text
OPENAI_API_KEY=your_real_key_here
OPENAI_MODEL=gpt-6-luna
```

6. Open `server.py` and press PyCharm's **Run ▶** button.
7. Open:

`http://127.0.0.1:8000`

The console should show the server address and whether Live AI is ON.

### Alternative

Open `start_server.py` and press **Run ▶**.

### Important

Do not upload `.env` to GitHub. The included `.gitignore` excludes it.
