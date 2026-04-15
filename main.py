from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import psycopg2
import psycopg2.extras
import os
import urllib.request
import urllib.parse
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://jamesdillingham.com", "https://www.jamesdillingham.com", "http://localhost"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

DATABASE_URL = os.environ.get("DATABASE_URL")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "Jim@shift-work.com")
APPROVE_SECRET = os.environ.get("APPROVE_SECRET", "cheapseats2026")
BASE_URL = os.environ.get("BASE_URL", "https://jamesdillingham-comments.onrender.com")
FORMSPREE_URL = os.environ.get("FORMSPREE_URL", "https://formspree.io/f/xzdypeyp")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY,
            post_slug TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT,
            body TEXT NOT NULL,
            approved BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS gratitude (
            id SERIAL PRIMARY KEY,
            gratitude_text TEXT NOT NULL,
            author_name TEXT,
            category TEXT,
            timestamp TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


init_db()


# ── MODELS ───────────────────────────────────────────────────────

class CommentIn(BaseModel):
    post_slug: str
    name: str
    email: str = ""
    body: str


class GratitudeIn(BaseModel):
    gratitude_text: str
    author_name: str | None = None
    category: str | None = None


# ── HELPERS ──────────────────────────────────────────────────────

def send_notification(comment_id: int, post_slug: str, name: str, body: str):
    approve_url = f"{BASE_URL}/approve?id={comment_id}&secret={APPROVE_SECRET}"
    reject_url = f"{BASE_URL}/reject?id={comment_id}&secret={APPROVE_SECRET}"

    try:
        payload = json.dumps({
            "email": NOTIFY_EMAIL,
            "_subject": f"New comment on '{post_slug}' — View from the Cheap Seats",
            "name": name,
            "post": post_slug,
            "comment": body,
            "approve_link": approve_url,
            "reject_link": reject_url
        }).encode("utf-8")

        req = urllib.request.Request(
            FORMSPREE_URL,
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
        print(f"Notification sent via Formspree for comment {comment_id}")
    except Exception as e:
        print(f"Formspree notification error: {e}")


# ── COMMENT ENDPOINTS ─────────────────────────────────────────────

@app.post("/comments")
def submit_comment(comment: CommentIn):
    if not comment.body.strip() or not comment.name.strip():
        raise HTTPException(status_code=400, detail="Name and comment are required.")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO comments (post_slug, name, email, body) VALUES (%s, %s, %s, %s) RETURNING id",
        (comment.post_slug, comment.name.strip(), comment.email.strip(), comment.body.strip())
    )
    comment_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    send_notification(comment_id, comment.post_slug, comment.name, comment.body)

    return {"status": "submitted", "message": "Your comment has been submitted for review. Thanks!"}


@app.get("/comments/{post_slug}")
def get_comments(post_slug: str):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT id, name, body, created_at FROM comments WHERE post_slug = %s AND approved = TRUE ORDER BY created_at ASC",
        (post_slug,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {"comments": [dict(r) for r in rows]}


@app.get("/approve")
def approve_comment(id: int = Query(...), secret: str = Query(...)):
    if secret != APPROVE_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret.")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE comments SET approved = TRUE WHERE id = %s", (id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "approved", "id": id}


@app.get("/reject")
def reject_comment(id: int = Query(...), secret: str = Query(...)):
    if secret != APPROVE_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret.")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM comments WHERE id = %s", (id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "rejected", "id": id}


# ── GRATITUDE ENDPOINTS ───────────────────────────────────────────

@app.get("/gratitude")
def get_gratitude():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT id, gratitude_text, author_name, category, timestamp FROM gratitude ORDER BY timestamp DESC LIMIT 500"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {"entries": [dict(r) for r in rows]}


@app.post("/gratitude")
def submit_gratitude(entry: GratitudeIn):
    text = (entry.gratitude_text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Gratitude text is required.")
    if len(text) > 500:
        raise HTTPException(status_code=400, detail="Entry must be 500 characters or fewer.")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO gratitude (gratitude_text, author_name, category) VALUES (%s, %s, %s) RETURNING id",
        (text, entry.author_name, entry.category)
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    return {"status": "ok", "id": new_id}


# ── LESSON ENDPOINT ───────────────────────────────────────────────

LESSON_SYSTEM_PROMPT = """You write crisp, intelligent short lessons. Pick ONE genuinely interesting topic completely at random from any domain: history, science, mathematics, language, food, psychology, geography, music, economics, nature, technology, philosophy, art, medicine, engineering, or anything else. Then write a compelling lesson about it in 300 words or fewer.

Return ONLY a JSON object with no markdown fences, no preamble:
{
  "category": "short category label (e.g. 'Natural Science', 'History', 'Psychology')",
  "title": "A sharp, specific title for the lesson",
  "paragraphs": ["paragraph 1", "paragraph 2", "paragraph 3"],
  "takeaway": "One memorable sentence the reader will remember tomorrow."
}

Rules:
- The topic must be genuinely random and varied across every possible domain. Surprise the reader.
- Total word count across all paragraphs must be 300 words or fewer.
- 3-4 paragraphs, each 60-90 words. Engaging, clear, no fluff.
- No bullet points. Prose only.
- The takeaway is a single elegant sentence.
- Return only the JSON object, nothing else."""


@app.post("/lesson")
def generate_lesson():
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="Lesson service not configured.")

    try:
        payload = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1000,
            "system": LESSON_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": "Give me a random lesson."}]
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01"
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        text = "".join(block.get("text", "") for block in data.get("content", []))
        clean = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        lesson = json.loads(clean)
        return lesson

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"Anthropic API error {e.code}: {error_body}")
        raise HTTPException(status_code=502, detail="Lesson generation failed.")
    except Exception as e:
        print(f"Lesson endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Lesson generation failed.")


# ── ROBOTS ───────────────────────────────────────────────────────

@app.get("/robots.txt")
def robots():
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


# ── HEALTH ───────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}
