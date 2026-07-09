"""StudySphere AI — REST API routes."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from auth import create_token, current_user_id, hash_password, verify_password
from db import get_db
from llm import (AGENTS, LLMError, generate_plan, generate_quiz,
                 learner_context, route_intent, specialist_reply)

router = APIRouter(prefix="/api")


# ---------- helpers ----------
def get_user(db, uid: int) -> dict:
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        raise HTTPException(404, "User not found")
    return dict(row)


def get_weak(db, uid: int) -> list[str]:
    rows = db.execute(
        "SELECT topic FROM weak_topics WHERE user_id=? ORDER BY misses DESC LIMIT 8", (uid,)
    ).fetchall()
    return [r["topic"] for r in rows]


def get_plan_full(db, uid: int):
    plan = db.execute("SELECT * FROM plans WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
    if not plan:
        return None
    tasks = db.execute(
        "SELECT id, day, topic, text, done FROM plan_tasks WHERE plan_id=? ORDER BY day, id",
        (plan["id"],),
    ).fetchall()
    days: dict[int, dict] = {}
    for t in tasks:
        days.setdefault(t["day"], {"day": t["day"], "topic": t["topic"], "tasks": []})
        days[t["day"]]["tasks"].append({"id": t["id"], "text": t["text"], "done": bool(t["done"])})
    return {"id": plan["id"], "subject": plan["subject"], "created": plan["created"],
            "items": list(days.values())}


def touch_streak(db, uid: int) -> dict:
    """Daily-login streak logic. Returns fresh user row."""
    user = get_user(db, uid)
    today = date.today().isoformat()
    if user["last_active"] != today:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        streak = user["streak"] + 1 if user["last_active"] == yesterday else 1
        db.execute("UPDATE users SET streak=?, last_active=? WHERE id=?", (streak, today, uid))
        user["streak"], user["last_active"] = streak, today
    return user


def llm_error(e: LLMError):
    return HTTPException(502, str(e))


# ---------- schemas ----------
class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    goal: str = Field(default="", max_length=200)
    grade: str = Field(default="", max_length=60)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class QuizGenIn(BaseModel):
    topic: str = Field(min_length=1, max_length=120)
    difficulty: str = Field(default="Medium", pattern="^(Easy|Medium|Hard)$")
    count: int = Field(default=5, ge=3, le=8)


class QuizSubmitIn(BaseModel):
    topic: str = Field(min_length=1, max_length=120)
    score: int = Field(ge=0)
    total: int = Field(ge=1, le=20)
    missed_topics: list[str] = Field(default_factory=list, max_length=20)


class PlanGenIn(BaseModel):
    subject: str = Field(min_length=1, max_length=120)
    days: int = Field(default=7, ge=2, le=21)
    hours: int = Field(default=2, ge=1, le=10)


class NoteIn(BaseModel):
    title: str = Field(default="Untitled", max_length=120)
    body: str = Field(default="", max_length=8000)


# ---------- auth ----------
@router.post("/auth/register")
def register(body: RegisterIn):
    with get_db() as db:
        exists = db.execute("SELECT 1 FROM users WHERE email=?", (body.email.lower(),)).fetchone()
        if exists:
            raise HTTPException(409, "An account with this email already exists — log in instead.")
        cur = db.execute(
            "INSERT INTO users (name, email, password_hash, goal, grade) VALUES (?,?,?,?,?)",
            (body.name.strip(), body.email.lower(), hash_password(body.password),
             body.goal.strip(), body.grade.strip()),
        )
        return {"token": create_token(cur.lastrowid)}


@router.post("/auth/login")
def login(body: LoginIn):
    with get_db() as db:
        row = db.execute("SELECT id, password_hash FROM users WHERE email=?",
                         (body.email.lower(),)).fetchone()
        if not row or not verify_password(body.password, row["password_hash"]):
            raise HTTPException(401, "Wrong email or password")
        return {"token": create_token(row["id"])}


# ---------- dashboard ----------
@router.get("/me")
def me(uid: int = Depends(current_user_id)):
    with get_db() as db:
        user = touch_streak(db, uid)
        quizzes = [dict(r) for r in db.execute(
            "SELECT topic, score, total, date FROM quizzes WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))]
        weak = [dict(r) for r in db.execute(
            "SELECT topic, misses FROM weak_topics WHERE user_id=? ORDER BY misses DESC LIMIT 8", (uid,))]
        avg = round(sum(q["score"] / q["total"] for q in quizzes) / len(quizzes) * 100) if quizzes else None
        total_quizzes = db.execute("SELECT COUNT(*) c FROM quizzes WHERE user_id=?", (uid,)).fetchone()["c"]
        return {
            "profile": {"name": user["name"], "goal": user["goal"], "grade": user["grade"]},
            "stats": {"xp": user["xp"], "streak": user["streak"],
                      "quiz_avg": avg, "quizzes_taken": total_quizzes},
            "recent_quizzes": quizzes,
            "weak_topics": weak,
            "plan": get_plan_full(db, uid),
        }


# ---------- chat (the agentic pipeline) ----------
@router.post("/chat")
async def chat(body: ChatIn, uid: int = Depends(current_user_id)):
    with get_db() as db:
        user = get_user(db, uid)
        weak = get_weak(db, uid)
        plan = db.execute("SELECT subject FROM plans WHERE user_id=? ORDER BY id DESC LIMIT 1",
                          (uid,)).fetchone()
        db.execute("INSERT INTO chats (user_id, role, content) VALUES (?,?,?)",
                   (uid, "user", body.message))
        history_rows = db.execute(
            "SELECT role, content FROM chats WHERE user_id=? ORDER BY id DESC LIMIT 12",
            (uid,)).fetchall()
    history = [{"role": r["role"], "content": r["content"]} for r in reversed(history_rows)]

    try:
        agent_key = await route_intent(body.message)                       # stage 1: router
        ctx = learner_context(user, weak, plan["subject"] if plan else None)
        reply = await specialist_reply(agent_key, history, ctx)            # stage 2: specialist
    except LLMError as e:
        raise llm_error(e)

    with get_db() as db:
        db.execute("INSERT INTO chats (user_id, role, agent, content) VALUES (?,?,?,?)",
                   (uid, "assistant", agent_key, reply))
        db.execute("UPDATE users SET xp = xp + 5 WHERE id=?", (uid,))
    a = AGENTS[agent_key]
    return {"agent": agent_key, "agent_name": a["name"], "icon": a["icon"],
            "color": a["color"], "reply": reply}


@router.get("/chat/history")
def chat_history(uid: int = Depends(current_user_id)):
    with get_db() as db:
        rows = db.execute(
            "SELECT id, role, agent, content, ts FROM chats WHERE user_id=? ORDER BY id DESC LIMIT 40",
            (uid,)).fetchall()
    out = []
    for r in reversed(rows):
        m = dict(r)
        if m["agent"] in AGENTS:
            a = AGENTS[m["agent"]]
            m.update({"agent_name": a["name"], "icon": a["icon"], "color": a["color"]})
        out.append(m)
    return {"messages": out}


# ---------- quizzes ----------
@router.post("/quiz/generate")
async def quiz_generate(body: QuizGenIn, uid: int = Depends(current_user_id)):
    with get_db() as db:
        weak = get_weak(db, uid)
    try:
        questions = await generate_quiz(body.topic, body.difficulty, body.count, weak)
    except LLMError as e:
        raise llm_error(e)
    return {"topic": body.topic, "questions": questions}


@router.post("/quiz/submit")
def quiz_submit(body: QuizSubmitIn, uid: int = Depends(current_user_id)):
    if body.score > body.total:
        raise HTTPException(422, "Score cannot exceed total")
    with get_db() as db:
        db.execute("INSERT INTO quizzes (user_id, topic, score, total) VALUES (?,?,?,?)",
                   (uid, body.topic, body.score, body.total))
        for t in body.missed_topics:
            t = t.strip().lower()[:60]
            if t:
                db.execute(
                    "INSERT INTO weak_topics (user_id, topic, misses) VALUES (?,?,1) "
                    "ON CONFLICT(user_id, topic) DO UPDATE SET misses = misses + 1",
                    (uid, t))
        db.execute("UPDATE users SET xp = xp + ? WHERE id=?", (body.score * 10, uid))
    return {"ok": True, "xp_gained": body.score * 10}


# ---------- study plan ----------
@router.post("/plan/generate")
async def plan_generate(body: PlanGenIn, uid: int = Depends(current_user_id)):
    with get_db() as db:
        weak = get_weak(db, uid)
    try:
        items = await generate_plan(body.subject, body.days, body.hours, weak)
    except LLMError as e:
        raise llm_error(e)
    with get_db() as db:
        db.execute("DELETE FROM plans WHERE user_id=?", (uid,))  # one active plan
        cur = db.execute("INSERT INTO plans (user_id, subject) VALUES (?,?)", (uid, body.subject))
        for item in items:
            for task in item.get("tasks", [])[:4]:
                db.execute("INSERT INTO plan_tasks (plan_id, day, topic, text) VALUES (?,?,?,?)",
                           (cur.lastrowid, int(item.get("day", 1)), str(item.get("topic", ""))[:120],
                            str(task)[:300]))
        return {"plan": get_plan_full(db, uid)}


@router.get("/plan")
def plan_get(uid: int = Depends(current_user_id)):
    with get_db() as db:
        return {"plan": get_plan_full(db, uid)}


@router.post("/plan/task/{task_id}/toggle")
def plan_toggle(task_id: int, uid: int = Depends(current_user_id)):
    with get_db() as db:
        row = db.execute(
            "SELECT pt.id, pt.done FROM plan_tasks pt JOIN plans p ON p.id=pt.plan_id "
            "WHERE pt.id=? AND p.user_id=?", (task_id, uid)).fetchone()
        if not row:
            raise HTTPException(404, "Task not found")
        new_done = 0 if row["done"] else 1
        db.execute("UPDATE plan_tasks SET done=? WHERE id=?", (new_done, task_id))
        if new_done:
            db.execute("UPDATE users SET xp = xp + 3 WHERE id=?", (uid,))
        return {"done": bool(new_done)}


@router.delete("/plan")
def plan_delete(uid: int = Depends(current_user_id)):
    with get_db() as db:
        db.execute("DELETE FROM plans WHERE user_id=?", (uid,))
    return {"ok": True}


# ---------- notes ----------
@router.get("/notes")
def notes_list(uid: int = Depends(current_user_id)):
    with get_db() as db:
        rows = db.execute("SELECT id, title, body, ts FROM notes WHERE user_id=? ORDER BY id DESC",
                          (uid,)).fetchall()
    return {"notes": [dict(r) for r in rows]}


@router.post("/notes")
def notes_add(body: NoteIn, uid: int = Depends(current_user_id)):
    with get_db() as db:
        cur = db.execute("INSERT INTO notes (user_id, title, body) VALUES (?,?,?)",
                         (uid, body.title.strip() or "Untitled", body.body))
        row = db.execute("SELECT id, title, body, ts FROM notes WHERE id=?", (cur.lastrowid,)).fetchone()
    return {"note": dict(row)}


@router.delete("/notes/{note_id}")
def notes_delete(note_id: int, uid: int = Depends(current_user_id)):
    with get_db() as db:
        db.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, uid))
    return {"ok": True}
