# Enki

A tutor that learns how you learn. It watches which explanations land for you — judged from your next message — builds a readable, editable profile of what works, and teaches you that way.

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

No key yet? Set `ENKI_FAKE_LLM=1` in `.env` — every model call is replaced by deterministic heuristics so the whole loop runs offline.

**Frontend**

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000  (backend URL: NEXT_PUBLIC_API_URL, default http://localhost:8000)
```

**Tests** — `cd backend && .venv/Scripts/python -m pytest` (runs the full loop against the fake model).

**After changing API models** — `cd backend && .venv/Scripts/python scripts/export_openapi.py ../frontend/openapi.json`, then `cd frontend && npm run gen:api`.

## How it works

1. **Workspace tree** — folders nest freely (CS → Data Structures); chats are leaves (Lec 7: Heaps). A chat's context is its own messages plus the summaries, patterns and "explanations that clicked" of the folders above it — never another chat's raw messages.
2. **Per turn** (background jobs) — the tagger (`claude-haiku-4-5`) labels *how* each tutor reply explained (analogy, example, formal definition, code…). When you reply, the evaluator judges from your message whether it landed. The chat shows this as the *learning lens*.
   - **Jev** (TypeSafe's classifier, `enki/evaluators.py`) is the evaluator when `TYPESAFE_API_KEY` is set. It gets `{learner_question, tutor_explanation, learner_next_message}` and answers four questions in one call: a 3-level **Score** (not understood / iffy / understood, with a probability for each), a **Choice** of what the reply shows (built on it, restated it, re-asked, confused…), and two yes/no probabilities (reused the tutor's wording; frustrated). If a Jev call fails it falls back to Claude.
   - Without a TypeSafe key, Claude (`claude-haiku-4-5`) judges instead. `ENKI_EVALUATOR=auto|jev|claude` overrides the choice.
   - Before trusting either, label some real turns and run `python scripts/compare_evaluators.py labelled.jsonl` (accuracy, confusion table, and Brier score for Jev's probabilities).
3. **Wrap up** — the reviewer (`claude-opus-5-5`) splits the session into concepts, finds where each clicked and which explanation did it (correcting for order effects), saves that explanation verbatim, and records evidence for or against patterns at the topic-folder level.
4. **Patterns** carry Beta(α, β) evidence counts. With ≥3 episodes and a clear lean either way they become **insight cards** you confirm or reject. You can also edit the markdown profile directly; the model translates your edit into pattern changes and tells you how it read it.
5. **The tutor** (`claude-sonnet-5-5`, streamed) gets the top patterns from the chat's folder chain (nearest folder wins), confirmed ones ranked first.

Model IDs, thresholds and the database URL are in `backend/enki/config.py` (overridable via `ENKI_*` env vars). Sonnet/Opus calls use server-side refusal fallbacks (`fallbacks: "default"`).

## MVP simplifications (vs. the plan)

- **Job queue**: a `jobs` table + one in-process worker thread instead of ARQ/Redis (`enki/jobs.py`; handlers are queue-agnostic).
- **Database**: SQLite by default; set `ENKI_DATABASE_URL` for Postgres. No pgvector yet (no embedding retrieval).
- **Single user, no auth.**
- **Not yet built**: pattern promotion up the tree / cross-topic transfer, exploration of non-favored strategies, weekly insight digests, retrieval checks.
