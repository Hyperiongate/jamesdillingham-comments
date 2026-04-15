from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
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
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


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
    conn.commit()
    cur.close()
    conn.close()


init_db()


class CommentIn(BaseModel):
    post_slug: str
    name: str
    email: str = ""
    body: str


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


@app.get("/health")
def health():
    return {"status": "ok"}


# ── /lesson proxy ──────────────────────────────────────────────
# Securely proxies requests to the Anthropic API so the key never
# lives in the browser or the static site repo.

@app.post("/lesson")
def generate_lesson():
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="Lesson service not configured.")

    system_prompt = (
        "You write crisp, intelligent short lessons. Pick ONE genuinely interesting topic "
        "completely at random from any domain: history, science, mathematics, language, food, "
        "psychology, geography, music, economics, nature, technology, philosophy, art, medicine, "
        "engineering, or anything else. Then write a compelling lesson about it in 300 words or fewer.\n\n"
        "Return ONLY a JSON object with no markdown fences, no preamble:\n"
        "{\n"
        '  "category": "short category label (e.g. \'Natural Science\', \'History\', \'Psychology\')",\n'
        '  "title": "A sharp, specific title for the lesson",\n'
        '  "paragraphs": ["paragraph 1", "paragraph 2", "paragraph 3"],\n'
        '  "takeaway": "One memorable sentence the reader will remember tomorrow."\n'
        "}\n\n"
        "Rules:\n"
        "- The topic must be genuinely random and varied. Surprise the reader.\n"
        "- Total word count across all paragraphs must be 300 words or fewer.\n"
        "- 3-4 paragraphs, each 60-90 words. Engaging, clear, no fluff.\n"
        "- No bullet points. Prose only.\n"
        "- The takeaway is a single elegant sentence.\n"
        "- Return only the JSON object, nothing else."
    )

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1000,
        "system": system_prompt,
        "messages": [{"role": "user", "content": "Give me a random lesson."}]
    }).encode("utf-8")

    try:
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
        clean = text.replace("```json", "").replace("```", "").strip()
        lesson = json.loads(clean)
        return lesson

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"Could not parse lesson JSON: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Lesson generation failed: {e}")
