# AI Council v0.1 — Personal prototype

A responsive, private, approval-gated multi-AI discussion app. **This is a prototype, not a hardened public production service.**

## Requirements
Python 3.10+ and internet access for real AI calls.

## Local setup
```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env  # Windows: copy .env.example .env
```
Edit `.env`: set `COUNCIL_PASSWORD` to a strong unique password. Leave `DEMO_MODE=true` to test without AI keys.

Start:
```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```
Open http://127.0.0.1:8000 and enter the panel password.

## Real AI mode
Add `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` in `.env`; change `DEMO_MODE=false`. You need provider API billing/credits and access to the configured model IDs. If a model is unavailable, change the relevant `*_MODEL` environment setting. **Do not share `.env` or paste keys into the web page.**

## Workflow
1. Create a project.
2. Click Run to get independent answers from the three providers.
3. Review and approve to permit the next round, or stop.
4. Next round asks each AI to critique the preceding responses. Maximum 3 rounds.
5. Records are stored in local SQLite `council.db`.

## Security / deployment
The password is sent via a custom request header and checked on every API call; use **HTTPS** for any remote deployment. The current UI retains the password only in the browser page's memory. For public internet deployment, add proper session-based authentication, rate limiting, CSRF protections as appropriate, request quotas, audit logging, backups, and a persistent hosted database. Restrict access with a VPN or access proxy until hardened. Do not expose the development server directly to the internet. The app has no automatic final consensus synthesis; the three responses are displayed side-by-side.

## Notes
The demo mode returns explicitly labeled placeholder text, not actual model results. Provider calls can incur costs. API failures are recorded in the response cards for troubleshooting. This is a single-user prototype without concurrency locks for simultaneous runs; avoid multiple browser sessions executing the same project at once.
