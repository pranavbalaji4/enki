# Enki

How you learn, read from your own conversations with Claude. Import your claude.ai history; Enki finds the chats where you were learning, judges whether each of Claude's explanations landed (from the message you sent next), sorts everything into a topic tree, and writes up what works for you — globally and per topic. Then ask it questions about how you learn.

```
backend/   Python · FastAPI · SQLAlchemy · Anthropic SDK   (port 8000)
frontend/  Next.js 16 · React 19 · Tailwind 4              (port 3000)
```

## Run it

**Backend**

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt        # macOS/Linux: .venv/bin/pip
cp .env.example .env                                  # add ANTHROPIC_API_KEY
.venv/Scripts/python -m uvicorn enki.api:app --port 8000
```

No key yet? Set `ENKI_FAKE_LLM=1` in `.env` — every model call is replaced by deterministic heuristics so the whole pipeline runs offline (the output is placeholder text).

**Frontend**

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000  (backend URL: NEXT_PUBLIC_API_URL, default http://localhost:8000)
```

**Your data** — in claude.ai: Settings → Privacy → Export data. Upload the ZIP on the Import page. The Anthropic API can't read claude.ai history, so the export is the only way in; your key is used only to analyze it. The Import page shows an upper-bound cost estimate before anything runs, and can analyze just your N most recent chats first.

**Tests** — `cd backend && .venv/Scripts/python -m pytest` (import → analysis → profile → Ask, against the fake model).

**After changing API models** — `cd backend && .venv/Scripts/python scripts/export_openapi.py ../frontend/openapi.json`, then `cd frontend && npm run gen:api`.

## How it works

An analysis run (`enki/analysis.py`) takes the imported, not-yet-analyzed chats through five resumable stages (2–6 below). Model calls run on a thread pool (`ENKI_ANALYSIS_CONCURRENCY`, `ENKI_REVIEW_CONCURRENCY`); results are written by the job's own thread.

1. **Import** (`enki/importer.py`) — parses `conversations.json`, keeps only the main branch of edited/retried conversations, and upserts by claude.ai id: re-uploading adds new chats and re-analyzes changed ones (their old evidence is taken back out first).
2. **Classify** (`claude-haiku-4-5`) — is this a learning chat or a task? Which domain and topic? Tasks are left out; you can include them from the chat page.
3. **Topics** (`claude-opus-5-5`) — merges the labels into a Domain → Topic tree, reusing existing names on later imports. Rename topics by double-clicking them in the sidebar.
4. **Turns** — for every Claude reply: how it explained (analogy, example, formal definition, code…) and whether it landed, judged from your next message as **understood / iffy / not understood** with a probability for each. The last reply of a chat has no next message and is marked `no_signal`.
   - **Jev** (TypeSafe's classifier, `enki/evaluators.py`) is the judge when `TYPESAFE_API_KEY` is set; its probabilities are calibrated. Otherwise Claude Haiku tags and judges in one call and gives its own (uncalibrated) estimate. `ENKI_EVALUATOR=auto|jev|claude` overrides. The chat page says which judge produced each badge.
5. **Review** (`claude-opus-5-5`) — splits each chat into concepts, finds where each clicked and which explanation did it, saves that explanation verbatim, and records Beta(α, β) evidence for patterns at the chat's topic.
6. **Profile** — topic summaries; patterns seen in two or more topics roll up into global patterns (evidence summed); Claude writes the global profile. Patterns with ≥3 episodes and a clear lean become "Does this sound like you?" cards; your answer outweighs any chat.

**Ask** (`enki/ask.py`, `claude-sonnet-5-5`, streamed) answers questions about how you learn with read-only tools over the analyzed data (profile, topics, a topic, search replies by text/level/topic, a chat) and links to the chats it used.

Model IDs, thresholds, prices for the estimate and the database URL are in `backend/enki/config.py` (overridable via `ENKI_*` env vars). Opus/Sonnet calls use server-side refusal fallbacks (`fallbacks: "default"`).

## MVP simplifications

- **Job queue**: a `jobs` table + one in-process worker thread instead of ARQ/Redis (`enki/jobs.py`).
- **Database**: SQLite by default; set `ENKI_DATABASE_URL` for Postgres. No migrations: new nullable columns are added on startup.
- **Single user, no auth.** Data stays local except what is sent to the Anthropic (and, with a key, TypeSafe) API.
- **Not yet built**: Claude Code transcripts as a second source, the Message Batches API for cheaper bulk analysis, deeper topic hierarchies, weekly digests.
