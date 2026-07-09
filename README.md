# StudySphere AI 🎓
**A 24×7 multi-agent AI study companion for school & college students.**
Full-stack: FastAPI backend + SQLite database + JWT auth + 8 AI agents on Groq.

## How it works
Every chat message goes through a real two-stage agentic pipeline on the backend:
1. **Router** (`llama-3.1-8b-instant`) classifies the student's intent
2. **Specialist agent** (`llama-3.3-70b-versatile`) answers with its own persona
   — Tutor 🎓, Academic Planner 🗺️, Quiz Agent ❓, Assignment Agent 📋 (hints only,
   never full homework answers), Research 🔬, Career Mentor 💼, Coding Mentor 💻,
   Productivity Coach ⚡

Agents share the student's live profile: streak, goal, grade, weak topics
(built automatically from quiz misses) and active study plan.

## Quick start (3 steps)

**Easiest (Windows):** double-click `start.bat`, then open http://localhost:8000
**Easiest (Mac/Linux):** run `./start.sh`, then open http://localhost:8000

**Manual (VS Code terminal):**
```bash
cd backend
pip install -r requirements.txt
copy .env.example .env      # Windows   (Mac/Linux: cp .env.example .env)
#  → open .env and paste your FREE key from https://console.groq.com/keys
python main.py
```
Then open **http://localhost:8000** in your browser — create an account and start learning.

> ⚠ **Do NOT use VS Code "Open with Live Server" on index.html.**
> Open http://localhost:8000 instead — the Python backend serves the app.
> (Live Server will now still work as a fallback — the page auto-connects to
> port 8000 — but only if the backend is running.)

## What's inside

```
backend/
  main.py        # FastAPI app, serves the frontend too
  routes.py      # all REST endpoints (auth, chat, quiz, plan, notes, dashboard)
  llm.py         # Groq client, 8 agent personas, router, JSON generators
  auth.py        # PBKDF2 password hashing + JWT sessions
  db.py          # SQLite schema (7 tables) — studysphere.db auto-created
  requirements.txt
  .env.example
frontend/
  index.html     # full SPA — dashboard, agent chat, quizzes, planner, notes
```

## Database tables
users · chats · quizzes · weak_topics · plans · plan_tasks · notes

## API summary
| Endpoint | Method | What it does |
|---|---|---|
| /api/auth/register, /api/auth/login | POST | JWT auth |
| /api/me | GET | dashboard: stats, streak, weak topics, plan |
| /api/chat | POST | router → specialist agent → saved reply |
| /api/chat/history | GET | last 40 messages |
| /api/quiz/generate, /api/quiz/submit | POST | live MCQs; misses feed weak topics |
| /api/plan/generate, /api/plan, /api/plan/task/{id}/toggle | POST/GET/POST | AI roadmap with persistent checkboxes |
| /api/notes | GET/POST/DELETE | notes CRUD |

## Notes
- Streak increments once per day on login; XP from chats (+5), quiz answers (+10 each), tasks (+3)
- The Assignment Agent is instructed to guide with steps and hints only — built for academic integrity
- Before deploying: set a strong JWT_SECRET in .env and restrict CORS origins in main.py
