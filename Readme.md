# jamesdillingham-comments

Comment moderation backend for jamesdillingham.com.

## Setup

### Environment Variables (set in Render dashboard)
- `DATABASE_URL` — your Render PostgreSQL internal URL
- `NOTIFY_EMAIL` — email to receive comment notifications
- `APPROVE_SECRET` — secret token for approve/reject links
- `BASE_URL` — the URL of this service on Render
- `SMTP_HOST` — your SMTP server (e.g. smtp.gmail.com)
- `SMTP_PORT` — usually 587
- `SMTP_USER` — your sending email address
- `SMTP_PASS` — your email app password

### Deploy
1. Push this repo to GitHub as `jamesdillingham-comments`
2. In Render: New → Web Service → connect repo
3. Set environment variables
4. Deploy

## API Endpoints

- `POST /comments` — submit a comment (goes to moderation)
- `GET /comments/{post_slug}` — get approved comments for a post
- `GET /approve?id=X&secret=Y` — approve a comment (linked in email)
- `GET /reject?id=X&secret=Y` — reject a comment (linked in email)
- `GET /health` — health check
