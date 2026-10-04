# 🎓 College Connect

**A privacy-first social platform exclusively for verified college students.**

College Connect is a full-stack web application that lets students anonymously share confessions, trade items in a campus marketplace, chat in real-time, and discover peers — all behind a verified `.ac.in` / `.edu` email wall. Built with a production-grade architecture deployed on Microsoft Azure.

> 🔗 **Live Demo:** [https://college-connect.azurecontainerapps.io](https://college-connect.azurecontainerapps.io)

---

## ✨ Features

### 🔐 Authentication & Security
- **Email-verified registration** with OTP (6-digit code via Azure Communication Services)
- **Google OAuth 2.0** sign-in for seamless onboarding
- **Dual-token architecture** — short-lived JWT access token + HttpOnly cookie refresh token for silent session renewal
- **Domain-restricted access** — only `.ac.in` and `.edu` emails are allowed to register
- **Sliding Window Rate Limiter** using Redis Sorted Sets (ZSET) to prevent brute-force attacks
- **Daily Upload Rate Limiter** to prevent storage abuse
- **Fail-Open design** — if Redis goes down, rate limiters gracefully allow traffic instead of crashing the app

### 💬 Real-Time Chat
- **WebSocket-powered** direct messaging with instant message delivery
- **Redis Pub/Sub** for scalable cross-instance message broadcasting
- **Typing indicators** and read receipts
- Conversations are persisted in MySQL with full message history

### 🤫 Anonymous Confessions
- Post confessions **completely anonymously** — no usernames, no traces
- **Dual-scope system**: Post to 🌐 **Global** (all campuses) or 🎓 **My College** (private to your campus only)
- College-scoped confessions are **invisible** to students from other colleges
- Like system with real-time like counts

### 🛒 Campus Marketplace (Bazaar)
- List items for sale with **image uploads** via Azure Blob Storage with SAS token authentication
- Express interest in listings — sellers get notified
- Delete your own listings

### 🔔 In-App Notifications
- Notification triggers: confession likes ❤️, marketplace interest 🛒, new messages 💬
- **Anti-spam logic** — duplicate unread notifications from the same user are suppressed
- **Self-action filtering** — you don't get notified for liking your own confession
- Unread badge counter on the navigation bell icon
- "Clear All" button to permanently delete notification history

### 👤 Student Profiles
- Customizable display name and profile picture
- Discover and browse other verified students on the platform

### 🚀 Launchpad
- Students can showcase side projects and apps they've built
- Community-driven project discovery across campuses

---

## 🏗️ Architecture

```
┌─────────────────────┐         ┌──────────────────────────────┐
│                     │  HTTPS  │                              │
│   Angular 21 SPA    │ ◄─────► │   FastAPI (Python) Backend   │
│   + Tailwind CSS    │   WSS   │   + SQLAlchemy ORM           │
│                     │         │   + Pydantic Validation      │
│  Azure Container    │         │                              │
│  Apps (Frontend)    │         │   Azure Container Apps       │
│                     │         │   (Backend)                  │
└─────────────────────┘         └──────────┬───────────────────┘
                                           │
                          ┌────────────────┼────────────────┐
                          │                │                │
                          ▼                ▼                ▼
                 ┌────────────┐   ┌────────────┐   ┌──────────────┐
                 │            │   │            │   │              │
                 │ Aiven MySQL│   │Redis Cloud │   │ Azure Blob   │
                 │ (Database) │   │  (Cache &  │   │   Storage    │
                 │            │   │ Rate Limit)│   │  (Images)    │
                 └────────────┘   └────────────┘   └──────────────┘
```

### Request Flow
1. User opens the Angular SPA → served from Azure Container Apps (Frontend)
2. Angular makes API calls over HTTPS / WebSocket (WSS) to the FastAPI backend
3. FastAPI authenticates via JWT, checks rate limits against Redis, queries MySQL via SQLAlchemy
4. For real-time chat: WebSocket connections are maintained per-user, with Redis Pub/Sub broadcasting messages across server instances
5. For file uploads: Backend generates a time-limited SAS URL → Angular uploads directly to Azure Blob Storage (zero backend bandwidth cost)

---

## 🛠️ Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Frontend** | Angular 21, Tailwind CSS, RxJS | Component-based SPA with reactive state management |
| **Backend** | FastAPI (Python), Uvicorn | Async-capable, auto-generated OpenAPI docs, Pydantic validation |
| **ORM** | SQLAlchemy | Database-agnostic, supports migrations, relationship management |
| **Database** | MySQL (Aiven Cloud) | ACID-compliant relational DB with managed backups |
| **Cache** | Redis Cloud (Free Tier) | Sub-millisecond caching, Pub/Sub for WebSockets, rate limiter storage |
| **Auth** | JWT + HttpOnly Cookies, Google OAuth 2.0 | Dual-token silent refresh, XSS-resistant refresh token storage |
| **File Storage** | Azure Blob Storage + SAS Tokens | Secure, scalable image hosting with direct-upload pattern |
| **Email** | Azure Communication Services | Transactional OTP emails with async delivery via BackgroundTasks |
| **Rate Limiting** | Custom Sliding Window (Redis ZSET) | Per-IP/user request throttling without external dependencies |
| **Monitoring** | Prometheus + Grafana Cloud | Real-time CPU, memory, and replica metrics |
| **Containerization** | Docker | Reproducible builds with multi-stage Dockerfiles |
| **Hosting** | Azure Container Apps | Serverless containers that scale to zero (cost-optimized) |

---

## 📁 Project Structure

### Backend (`college-connect-backend/`)
```
app/
├── api/                    # Route handlers
│   ├── auth.py             # Registration, login, OTP, Google OAuth, password reset
│   ├── chat.py             # WebSocket chat + REST conversation endpoints
│   ├── confessions.py      # CRUD + like system with scope filtering
│   ├── marketplace.py      # Item listings with image upload + interest system
│   ├── notifications.py    # Notification CRUD + unread count + clear all
│   ├── profiles.py         # Student profile management
│   └── launchpad.py        # Student app showcase
├── core/
│   ├── config.py           # Pydantic Settings (env vars)
│   ├── security.py         # JWT creation, password hashing
│   ├── rate_limiter.py     # SlidingWindowRateLimiter + DailyUploadRateLimiter
│   ├── redis.py            # Async Redis connection pool
│   ├── email_client.py     # Azure Email Service wrapper
│   └── dependencies.py     # FastAPI dependency injection
├── db/
│   ├── models.py           # SQLAlchemy models (User, Confession, Message, etc.)
│   └── session.py          # Database engine + session factory
├── schemas/                # Pydantic request/response schemas
└── main.py                 # App entrypoint + CORS + Prometheus instrumentation
```

### Frontend (`college-connect-frontend/`)
```
src/app/
├── features/
│   ├── authentication/     # Login, Register, OTP verification, Password reset
│   ├── feed/               # Confessions + Launchpad (Global / My College toggle)
│   ├── chat/               # WebSocket real-time messaging
│   ├── marketplace/        # Campus Bazaar with image uploads
│   ├── notifications/      # Notification center with Clear All
│   ├── profile/            # User profile editing
│   └── home/               # Landing page
├── core/
│   ├── services/           # AuthService, CurrentUserService
│   └── api.config.ts       # API base URL configuration
└── app.ts                  # Root component with nav, theme toggle, notification badge
```

---

## 🔒 Security Highlights

| Threat | Mitigation |
|--------|-----------|
| Brute-force login | Sliding Window Rate Limiter (Redis ZSET) — configurable requests/window |
| XSS token theft | Refresh token stored in HttpOnly cookie (inaccessible to JavaScript) |
| Unauthorized access | Domain-restricted registration (`.ac.in` / `.edu` only) |
| Image upload abuse | Daily upload rate limiter + file extension whitelist |
| SQL Injection | SQLAlchemy ORM with parameterized queries |
| CORS exploitation | Strict origin allowlist in FastAPI middleware |
| Redis downtime | Fail-Open rate limiters — app stays available if cache is down |

---

## 💰 Cost Optimization

This project is architected to run at **near-zero cost** on cloud infrastructure:

- **Azure Container Apps** — scales to zero when idle (no traffic = no bill)
- **Aiven MySQL** — managed DB at ~$0.10/month on the smallest tier
- **Redis Cloud** — 30MB free tier (more than enough for caching + rate limiting)
- **Azure Blob Storage** — 5GB free tier for image hosting
- **Navigation-based notification polling** instead of interval-based polling to allow containers to sleep
- **Async email delivery** via FastAPI BackgroundTasks to prevent blocking the event loop

---

## 🚀 Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+
- Angular CLI (`npm install -g @angular/cli`)
- Redis (local or cloud)
- MySQL (local or cloud)

### Backend Setup
```bash
cd college-connect-backend

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL, JWT_SECRET_KEY, REDIS_URL, etc.

# Run the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend Setup
```bash
cd college-connect-frontend

# Install dependencies
npm install

# Start dev server
ng serve
```

Open `http://localhost:4200` in your browser.

---

## 📊 Monitoring

The backend exposes a `/metrics` endpoint via `prometheus-fastapi-instrumentator`. Connected to **Grafana Cloud** for real-time dashboards tracking:
- Active replicas and autoscaling events
- CPU and memory utilization
- HTTP request rates and latency percentiles

---

## 🗺️ Roadmap

- [ ] CI/CD pipeline with GitHub Actions
- [ ] Client-side image compression before upload
- [ ] Infinite scroll (Intersection Observer) for confessions feed
- [ ] Marketplace categories and search
- [ ] Typing indicators in chat

---

## 📄 License

This project is built for educational and portfolio purposes.

---

<p align="center">
  <b>Built with ❤️ by <a href="https://github.com/Shreyash203">Shreyash Bhanage</a></b>
</p>
