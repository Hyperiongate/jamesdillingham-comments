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
FORMSPREE_URL = os.environ.get("FORMSPREE_URL", "https://formspree.io/f/xwvwnwea")


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
