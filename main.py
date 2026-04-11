from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import psycopg2
import psycopg2.extras
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://jamesdillingham.com", "https://www.jamesdillingham.com", "http://localhost"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

DATABASE_URL = os.environ.get("DATABASE_URL")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "Jim@shift-work.com")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
APPROVE_SECRET = os.environ.get("APPROVE_SECRET", "changeme")
BASE_URL = os.environ.get("BASE_URL", "https://comments-api.onrender.com")


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
    if not SMTP_USER or not SMTP_PASS:
        print("SMTP not configured — skipping email notification")
        return

    approve_url = f"{BASE_URL}/approve?id={comment_id}&secret={APPROVE_SECRET}"
    reject_url = f"{BASE_URL}/reject?id={comment_id}&secret={APPROVE_SECRET}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"New comment on '{post_slug}' — View from the Cheap Seats"
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_EMAIL

    html = f"""
    <h2>New comment on post: <em>{post_slug}</em></h2>
    <p><strong>From:</strong> {name}</p>
    <p><strong>Comment:</strong><br>{body}</p>
    <br>
    <p>
      <a href="{approve_url}" style="background:#c0392b;color:white;padding:10px 20px;text-decoration:none;border-radius:4px;margin-right:10px;">
        ✓ Approve
      </a>
      <a href="{reject_url}" style="background:#666;color:white;padding:10px 20px;text-decoration:none;border-radius:4px;">
        ✗ Reject
      </a>
    </p>
    """

    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, NOTIFY_EMAIL, msg.as_string())
    except Exception as e:
        print(f"Email error: {e}")


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
