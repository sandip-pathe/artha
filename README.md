# Artha Backend (PayGuard)

FastAPI backend for the Artha WhatsApp merchant assistant.

## Quick Goal (30 Minutes)

If you are in the last hour, do this in order:

1. Push current code to GitHub.
2. Create Railway project from GitHub repo.
3. Add required environment variables.
4. Deploy and check `/health`.
5. Update Meta webhook URL to Railway domain `/webhook`.
6. Test one text message and one image message on WhatsApp.

Do **hosting first**. Do not add new features now.

## Required Environment Variables

Use `.env.example` as source of truth.

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `WHATSAPP_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_VERIFY_TOKEN`

Optional:

- `OPENAI_TTS_MODEL`
- `OPENAI_TTS_VOICE`
- `GOOGLE_APPLICATION_CREDENTIALS` (only if using Google Vision service account file path)
- `WHATSAPP_PAYTM_TEMPLATE`
- `WHATSAPP_TEMPLATE_LANG`

## Run Locally

```bash
c:/x/pay-gaurd/.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --env-file .env
```

Health check:

```bash
curl http://127.0.0.1:8010/health
```

## Railway Deploy (GitHub Flow)

The repo includes:

- `Procfile`
- `railway.json`

Steps:

1. Push code to GitHub.
2. In Railway: `New Project` -> `Deploy from GitHub Repo`.
3. Add all required env vars in Railway service settings.
4. Deploy.
5. Open generated domain and verify:

```bash
curl https://<your-railway-domain>/health
```

## Meta Webhook Setup

1. Set callback URL to:

`https://<your-railway-domain>/webhook`

2. Verify token must match `WHATSAPP_VERIFY_TOKEN`.
3. Subscribe to message events.

## One-Day Reliability Checklist

1. Use long-lived/system-user `WHATSAPP_TOKEN` (not a short-lived explorer token).
2. Keep Railway service on plan that does not sleep.
3. Keep DB on persistent managed Postgres.
4. Confirm `/health` periodically.
5. Avoid further code changes during demo window.
