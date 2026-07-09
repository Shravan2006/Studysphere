"""StudySphere AI — agent brain, powered by Groq.

Two-stage agentic pipeline:
  1. ROUTER  — llama-3.1-8b-instant classifies intent → picks a specialist
  2. SPECIALIST — llama-3.3-70b-versatile answers with that agent's persona
     + the student's live learner profile (streak, weak topics, goal).
"""
import json
import os
import re

import httpx
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
MODEL_MAIN = os.getenv("GROQ_MODEL_MAIN", "llama-3.3-70b-versatile")
MODEL_FAST = os.getenv("GROQ_MODEL_FAST", "llama-3.1-8b-instant")

AGENTS = {
    "planner": {
        "name": "Academic Planner", "icon": "🗺️", "color": "#F5B14C",
        "sys": "You are the Academic Planner agent in StudySphere, helping school and college students. Break subjects into structured roadmaps, estimate study time, sequence topics by prerequisites, and prioritize the student's weak topics. Be concrete with day-by-day structure. Under 250 words.",
    },
    "tutor": {
        "name": "Tutor", "icon": "🎓", "color": "#8B7CF6",
        "sys": "You are the Tutor agent in StudySphere. Explain concepts like a brilliant, patient teacher: intuition first, then precision. Adapt to the student's grade level. Always use one concrete example or analogy. End with one short check-understanding question. Under 300 words.",
    },
    "quiz": {
        "name": "Quiz Agent", "icon": "❓", "color": "#5EC8E5",
        "sys": "You are the Quiz agent in StudySphere. Test understanding with sharp questions and explain answers. For a full interactive quiz, point the student to the Quizzes tab, then give 2-3 questions inline. Under 250 words.",
    },
    "assignment": {
        "name": "Assignment Agent", "icon": "📋", "color": "#4ADE9C",
        "sys": "You are the Assignment agent in StudySphere. STRICT RULE: never provide complete solutions to homework or assignments. Break the problem into steps, give hints, explain the underlying concept, and offer to review the student's own attempt. If pushed for the full answer, kindly explain why you guide instead of solve. Under 250 words.",
    },
    "research": {
        "name": "Research Agent", "icon": "🔬", "color": "#5EC8E5",
        "sys": "You are the Research agent in StudySphere. Synthesize knowledge: clear definitions, key ideas, competing viewpoints, and where to read more. Be honest about uncertainty. Under 300 words.",
    },
    "career": {
        "name": "Career Mentor", "icon": "💼", "color": "#F5B14C",
        "sys": "You are the Career Mentor agent in StudySphere for students. Advise on streams, courses, projects, internships, resumes, interviews, and skill gaps. Be specific and actionable. Under 300 words.",
    },
    "coding": {
        "name": "Coding Mentor", "icon": "💻", "color": "#8B7CF6",
        "sys": "You are the Coding Mentor agent in StudySphere. Debug code, explain errors, teach programming (Python, Java, JS, DSA, web dev, AI basics). Show minimal snippets and explain the WHY so the bug never happens again. Under 350 words.",
    },
    "coach": {
        "name": "Productivity Coach", "icon": "⚡", "color": "#4ADE9C",
        "sys": "You are the Productivity Coach agent in StudySphere. Help with motivation, focus, exam stress, burnout prevention, Pomodoro planning and daily goals. Warm but no fluff — always give one concrete next action. Reference their streak when relevant. Under 200 words.",
    },
}

ROUTER_SYS = (
    "You are the intent router for a multi-agent study platform for students. "
    "Classify the message to exactly one agent key: "
    "planner (study schedules/roadmaps/timetables), tutor (explain concepts/doubts), "
    "quiz (wants to be tested), assignment (homework help), research (deep topics/sources), "
    "career (streams/jobs/internships/resume), coding (code/debugging/programming), "
    "coach (motivation/focus/procrastination/stress). "
    'Respond ONLY with JSON: {"agent":"key"}'
)


class LLMError(Exception):
    pass


async def groq_chat(system: str, messages: list[dict], model: str = None,
                    max_tokens: int = 900, json_mode: bool = False) -> str:
    """Call Groq's OpenAI-compatible chat completions endpoint."""
    if not GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is not set. Add it to backend/.env (get a free key at console.groq.com).")
    body = {
        "model": model or MODEL_MAIN,
        "max_tokens": max_tokens,
        "temperature": 0.6,
        "messages": [{"role": "system", "content": system}] + messages,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{GROQ_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json=body,
            )
    except httpx.HTTPError:
        raise LLMError("Could not reach Groq — check your internet connection and try again.")
    if r.status_code == 401:
        raise LLMError("Groq rejected the API key. Check GROQ_API_KEY in backend/.env.")
    if r.status_code == 429:
        raise LLMError("Groq rate limit hit — wait a few seconds and try again.")
    if r.status_code >= 400:
        raise LLMError(f"Groq API error {r.status_code}: {r.text[:200]}")
    data = r.json()
    return data["choices"][0]["message"]["content"]


def extract_json(text: str) -> dict:
    text = re.sub(r"```json|```", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


async def route_intent(message: str) -> str:
    try:
        out = await groq_chat(ROUTER_SYS, [{"role": "user", "content": message}],
                              model=MODEL_FAST, max_tokens=40, json_mode=True)
        key = extract_json(out).get("agent", "tutor")
        return key if key in AGENTS else "tutor"
    except LLMError:
        raise
    except Exception:
        return "tutor"


def learner_context(user: dict, weak: list[str], plan_subject: str | None) -> str:
    weak_str = ", ".join(weak[:6]) or "none identified yet"
    return (
        f"LEARNER PROFILE — name: {user['name']}; grade/level: {user.get('grade') or 'not given'}; "
        f"goal: {user.get('goal') or 'general study'}; streak: {user['streak']} days; "
        f"weak topics from quiz misses: {weak_str}; active study plan: {plan_subject or 'none'}. "
        "Personalize with this, referencing it only when genuinely relevant."
    )


async def specialist_reply(agent_key: str, history: list[dict], profile_ctx: str) -> str:
    agent = AGENTS[agent_key]
    return await groq_chat(agent["sys"] + "\n\n" + profile_ctx, history, model=MODEL_MAIN)


async def generate_quiz(topic: str, difficulty: str, count: int, weak: list[str]) -> list[dict]:
    weak_hint = f" The student is weak in: {', '.join(weak[:4])} — bias toward these if relevant." if weak else ""
    sys = (
        f"You are the Quiz agent. Generate exactly {count} {difficulty.lower()} multiple-choice "
        f'questions on "{topic}".{weak_hint} Respond ONLY with JSON: '
        '{"questions":[{"q":"...","options":["A","B","C","D"],"answer":0,'
        '"topic":"one-or-two-word subtopic","explanation":"one terse sentence"}]} '
        "answer is the 0-based index of the correct option. Keep every string short."
    )
    out = await groq_chat(sys, [{"role": "user", "content": "Generate the quiz now."}],
                          max_tokens=1400, json_mode=True)
    questions = extract_json(out).get("questions", [])
    if not questions:
        raise LLMError("Quiz generation returned no questions — try again.")
    return questions


async def generate_plan(subject: str, days: int, hours: int, weak: list[str]) -> list[dict]:
    weak_hint = f" Front-load the student's weak topics where relevant: {', '.join(weak[:4])}." if weak else ""
    sys = (
        f'You are the Academic Planner agent. Build a {days}-day study roadmap for "{subject}" '
        f"at {hours} hours/day.{weak_hint} Respond ONLY with JSON: "
        '{"items":[{"day":1,"topic":"short topic","tasks":["task","task","task"]}]} '
        f"Exactly {days} items, 2-3 terse tasks each."
    )
    out = await groq_chat(sys, [{"role": "user", "content": "Generate the plan now."}],
                          max_tokens=1600, json_mode=True)
    items = extract_json(out).get("items", [])
    if not items:
        raise LLMError("Plan generation returned no items — try again.")
    return items
