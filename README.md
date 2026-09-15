<div align="center">

<br/>

<a href="https://git.io/typing-svg">
  <img src="https://readme-typing-svg.herokuapp.com?font=Fira+Code&weight=600&size=30&pause=1000&color=218B8D&center=true&vCenter=true&width=560&lines=Job+Watcher;Watch.+Score.+Apply.+Follow+up." alt="Typing SVG" />
</a>

<br/>

<p>
  <img src="https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/Django-5.2-092E20?style=flat-square&logo=django&logoColor=white"/>
  <img src="https://img.shields.io/badge/DRF-3.18-A30000?style=flat-square&logo=django&logoColor=white"/>
  <img src="https://img.shields.io/badge/React-19-20232A?style=flat-square&logo=react&logoColor=61DAFB"/>
  <img src="https://img.shields.io/badge/TypeScript-5-007ACC?style=flat-square&logo=typescript&logoColor=white"/>
  <img src="https://img.shields.io/badge/Vite-7-646CFF?style=flat-square&logo=vite&logoColor=white"/>
  <img src="https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white"/>
  <img src="https://img.shields.io/badge/Windows-desktop-0078D4?style=flat-square&logo=windows&logoColor=white"/>
  <img src="https://img.shields.io/badge/macOS-desktop-000000?style=flat-square&logo=apple&logoColor=white"/>
</p>

</div>

<br/>

---

## `~/about`

```ts
const jobWatcher = {
  type:        "Cross-platform desktop app (Windows · macOS)",
  backend:     ["Python 3.13", "Django 5.2", "Django REST Framework", "SQLite", "APScheduler", "pytest"],
  frontend:    ["React 19", "TypeScript", "Vite", "TanStack Query", "React Router", "Vitest"],
  desktop:     ["waitress", "pywebview (WebView2 · WKWebView)", "pystray", "C# launcher · .app bundle"],
  features:    ["Scheduled job checks", "Profile scoring", "Applications list", "AI cover letters", "Application detection", "Tray notifications"],
  sources:     "Brazil-first · InHire · Gupy · GitHub Issues",
  author:      "Mauro Junior · github.com/mj01px",
} as const;
```

**Job Watcher** watches developer job sources for you, scores every posting against your
own profile, and keeps track of each application until an answer comes. It solves the
two chores of a job hunt that eat the most time: **opening dozens of career pages every
day** and **remembering who never answered**.

It runs as a desktop app that lives in the tray (notification area on Windows, menu bar
on macOS). Four times a day it checks 74 InHire career pages, 38 Gupy searches and 4 GitHub
vacancy repositories, highlights what matches your stack, and tells you when something new
is worth a look.

```
jobwatcher/
├── backend/     # Django REST API + check worker   →  http://127.0.0.1:8000
├── frontend/    # React + Vite SPA                  →  http://localhost:5173
├── desktop/     # Tray app: API, worker and window in one process
│                #   platform_support.py isolates the Windows/macOS/Linux specifics
└── scripts/     # desktop.bat → JobWatcher.exe (Windows) · desktop.sh → JobWatcher.app (macOS)
```

---

## `~/features`

<table>
  <tr>
    <td valign="top" width="50%">
      <b>🎯 Job hunting</b><br/><br/>
      <ul>
        <li>Checks at 09:00, 12:00, 15:00 and 18:00, with a catch up after the PC was off</li>
        <li>Every job scored against weighted term groups you edit in the app</li>
        <li>Highlights only when the score is high <b>and</b> the job matches your stack</li>
        <li>"New" means new since your last visit, not since the last check</li>
        <li>Jobs that close at the source are archived, never deleted</li>
        <li>Manual entry for what the sources miss</li>
        <li>Each source shows its yield, so dead ones can be paused</li>
      </ul>
    </td>
    <td valign="top" width="50%">
      <b>📬 Applications</b><br/><br/>
      <ul>
        <li>One list ordered by how long each application waits for an answer</li>
        <li>Groups for 10+ days, 2 to 9 days, and today or yesterday</li>
        <li>Stage, next step and "got an answer" right on the row</li>
        <li>Detail drawer with stage blocks, follow up and a timeline</li>
        <li>AI cover letter per job, written from your own dossier</li>
      </ul>
      <br/>
      <b>🖥️ Desktop</b><br/><br/>
      <ul>
        <li>Lives in the tray; closing the window keeps the checks running</li>
        <li>Windows notifications for new highlights and overdue follow ups</li>
        <li>InHire jobs open in an app window that records the application by itself</li>
        <li>Starts hidden with Windows</li>
      </ul>
    </td>
  </tr>
</table>

---

## `~/getting-started`

### Backend

```bash
cd backend

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt

copy .env.example .env          # enables DJANGO_DEBUG for development

python manage.py migrate
python manage.py runserver 127.0.0.1:8000
python manage.py run_worker        # second terminal: scheduled checks and "check now"
```

### Frontend

```bash
cd frontend
corepack pnpm install && corepack pnpm dev      # → http://localhost:5173
```

### Desktop app (Windows)

```bash
scripts\desktop.bat             # once: builds desktop\JobWatcher.exe + shortcuts
```

Creates a **Job Watcher** shortcut on the Desktop, in the Start menu and in the Startup
folder. The app runs Django on waitress at `127.0.0.1:17843`, the check worker on a thread,
and the dashboard in a WebView2 window, with an icon in the notification area. Closing the
window only hides it; **Sair** in the tray menu stops everything.

Code changes need no rebuild: the exe only launches `desktop\app.py`, which applies pending
migrations and rebuilds the frontend when something under `frontend/src` changed. Database,
API keys, backups and the session log live in `%LOCALAPPDATA%\JobWatcher`.

### Desktop app (macOS)

```bash
python3 -m venv backend/.venv                        # once
scripts/desktop.sh              # builds desktop/JobWatcher.app (needs frontend deps installed)
```

Open **JobWatcher.app** from Launchpad or Spotlight (`scripts/desktop.sh` installs it into
`/Applications`). Same app: Django on waitress at `127.0.0.1:17843`, the worker on a thread
and the dashboard in a native WKWebView window. On macOS it is a **Dock app**, not a tray
app: **closing the window or Cmd+Q quits it**; **minimise** it (or the *Abrir ao iniciar o
Mac* LaunchAgent) to keep the checks running in the background. **Verificar agora**,
notifications and open-at-login live in the **Job Watcher menu** at the top of the screen.
Data, keys, backups and the session log live in `~/Library/Application Support/JobWatcher`.

Everything OS-specific — data directory, single-instance port lock, autostart, notifications,
native dialogs and the Dock identity — lives in `desktop/platform_support.py`, so Windows and
macOS share one `app.py`. Windows keeps its notification-area tray icon; macOS uses the native
menu (pystray's status-bar backend is unreliable under pywebview). Linux uses the same code
path (XDG data dir, `.desktop` autostart) and runs from `backend/.venv/bin/python
desktop/app.py` after `scripts/desktop.sh`.

---

## `~/environment`

Development reads `backend/.env`. The desktop app configures itself and needs no file.

```env
DJANGO_DEBUG=true
DJANGO_SECRET_KEY=              # required when DJANGO_DEBUG is off

# Timezone for the daily checks
JOB_WATCHER_TIMEZONE=America/Sao_Paulo

# Directory that holds the SQLite database (default: backend/data)
JOB_WATCHER_DATA_DIR=
```

<details>
<summary><b>API keys and optional overrides</b></summary>
<br/>

API keys are normally saved from **Settings** into `<data dir>/secrets.json`, never into the
database and never returned by the API. Environment variables win when set.

```env
# Google AI Studio key, used to write the cover letters
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.7-flash

# Personal GitHub token, public scope is enough
# Without it the API allows 60 requests/hour, with it 5000
GITHUB_TOKEN=

# Gupy portal endpoint, only if it ever moves
GUPY_API=https://employability-portal.gupy.io/api/v1/jobs

# Built frontend served by Django (default: ../frontend/dist)
JOB_WATCHER_FRONTEND_DIST=
JOB_WATCHER_LOG_LEVEL=INFO
```

</details>

---

## `~/commands`

```bash
python manage.py run_worker                 # scheduler + executor of queued checks
python manage.py run_worker --once          # process the queue and exit
python manage.py rescore                    # reapply the scoring profile to every job
python manage.py fetch_inhire_details       # backfill InHire job descriptions
python manage.py import_vaggio <file>       # bring jobs, applications and dossier from a Vaggio database
```

---

## `~/how-it-works`

<details>
<summary><b>Checks: when a job counts as closed</b></summary>
<br/>

The web process never collects jobs. "Check now" queues a check run and the worker executes
it, writing progress per source to the database so the activity page can show it live.

The first successful check of a source is its **baseline**: existing jobs are not new. After
that, the rule for archiving is about **confidence**, never about a job simply missing:

- **InHire** returns the whole career page, so a job that disappears is archived;
- **GitHub** is trusted only when every page of open issues was read;
- **Gupy** is a search, so absence proves nothing and jobs expire after 30 days instead.

A failed or unconfirmed collection never archives anything, and an archived job that comes
back is reopened and marked new. InHire listings carry titles only, so the collector also
reads each job's public page to score it on the full description.

</details>

<details>
<summary><b>Scoring: what makes a job highlighted</b></summary>
<br/>

Terms are grouped by weight: the stack you want, the domain where your experience is worth
more, the seniority that fits, and penalties for the ones that do not. A hit in the **title
counts double**, **one hit per group** is enough, and asking for **too many years of
experience subtracts**.

A score alone was not enough: on real data most "highlights" were finance or support roles
that never mentioned a technology. So a job is highlighted only when it reaches the minimum
score **and** hits a group marked as stack. Groups, weights, stack groups and the minimum
score are edited in **Settings**, and saving rescores every job at once.

</details>

<details>
<summary><b>Applications: detecting what you sent</b></summary>
<br/>

InHire has no candidate area to read back, but its apply form posts to a public route whose
path carries the job id. In the desktop app, InHire jobs open in their own window with a small
hook around `fetch` and `XMLHttpRequest`: a successful `POST` to that route for that exact job
moves it into the list as applied, adds a timeline entry and shows a notification. Anywhere
else, "Applied" on the row does the same by hand.

</details>

<details>
<summary><b>API</b></summary>
<br/>

Everything under `/api/v1/`, with the same envelope on every response
`{ data, error, meta: { requestId } }`. Unsafe methods require the CSRF token. The full
contract lives in [`docs/API.md`](docs/API.md).

| Route | What it does |
|---|---|
| `GET /status` | Current check, progress per source, next scheduled run, worker heartbeat |
| `GET /overview` | Counters and recent highlights |
| `GET /jobs?view=all\|highlighted\|archived` | Paginated lists |
| `POST /jobs` · `GET /jobs/{id}` | Manual entry and job detail |
| `POST /jobs/{id}/archive` · `/restore` · `/visit` | Triage |
| `POST /jobs/{id}/application` | Put a job in the applications list |
| `GET/POST /jobs/{id}/pitch` | Cover letter for a job |
| `GET /applications/board` · `/closed` | Active and closed applications |
| `PATCH/DELETE /applications/{id}` · `POST .../interactions` | Stage, next step, timeline |
| `GET/POST/PATCH/DELETE /sources` | InHire pages, Gupy searches, GitHub repositories |
| `GET/PUT /settings/scoring` · `/profile` · `PUT /settings/secrets` | Scoring, dossier, API keys |
| `POST /check-runs` · `POST /visits` | Check now, visit sessions |

</details>

---

## `~/tests`

```bash
cd backend && pytest && ruff check .                 # 407 tests
cd frontend && corepack pnpm typecheck && corepack pnpm test   # 109 tests
```

The suite covers the API, the collectors with mocked HTTP (pagination, retries, the
archiving rules), the scoring engine, the worker and scheduler, the applications flow, the
cover letters with the model mocked, the Vaggio import, the desktop platform layer
(`platform_support`: data dirs, autostart, the port lock), and on the frontend the grouping
of applications, the visit pings and the desktop bridge.

---

## `~/stack`

<div align="center">

| Layer | Technologies |
|-------|-------------|
| **Backend** | ![Python](https://img.shields.io/badge/Python_3.13-3776AB?style=flat-square&logo=python&logoColor=white) ![Django](https://img.shields.io/badge/Django_5.2-092E20?style=flat-square&logo=django&logoColor=white) ![DRF](https://img.shields.io/badge/DRF-A30000?style=flat-square&logo=django&logoColor=white) ![pytest](https://img.shields.io/badge/pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white) |
| **Frontend** | ![React](https://img.shields.io/badge/React_19-20232A?style=flat-square&logo=react&logoColor=61DAFB) ![TypeScript](https://img.shields.io/badge/TypeScript-007ACC?style=flat-square&logo=typescript&logoColor=white) ![Vite](https://img.shields.io/badge/Vite-646CFF?style=flat-square&logo=vite&logoColor=white) ![React Query](https://img.shields.io/badge/TanStack_Query-FF4154?style=flat-square&logo=reactquery&logoColor=white) |
| **Desktop** | ![Windows](https://img.shields.io/badge/Windows-0078D4?style=flat-square&logo=windows&logoColor=white) ![macOS](https://img.shields.io/badge/macOS-000000?style=flat-square&logo=apple&logoColor=white) ![WebView2](https://img.shields.io/badge/WebView2-0078D7?style=flat-square&logo=microsoftedge&logoColor=white) ![WKWebView](https://img.shields.io/badge/WKWebView-000000?style=flat-square&logo=safari&logoColor=white) ![pywebview](https://img.shields.io/badge/pywebview-1a1a1a?style=flat-square) |
| **Database** | ![SQLite](https://img.shields.io/badge/SQLite_WAL-003B57?style=flat-square&logo=sqlite&logoColor=white) |
| **AI** | ![Gemini](https://img.shields.io/badge/Google_Gemini-8E75B2?style=flat-square&logo=googlegemini&logoColor=white) |
| **Sources** | ![InHire](https://img.shields.io/badge/InHire-218B8D?style=flat-square&logoColor=white) ![Gupy](https://img.shields.io/badge/Gupy-00B37E?style=flat-square&logoColor=white) ![GitHub](https://img.shields.io/badge/GitHub_Issues-181717?style=flat-square&logo=github&logoColor=white) |

</div>

---

<div align="center">
  <br/>
  <sub>
    Built by <a href="https://github.com/mj01px"><strong>Mauro Junior</strong></a>
    &nbsp;·&nbsp;
    <a href="https://www.linkedin.com/in/mauroapjunior/">LinkedIn</a>
  </sub>
  <br/><br/>
</div>
