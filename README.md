# Interview

Standalone FastAPI backend for the "Interview Andres" chatbot on Andres Blanco's portfolio website.

The API answers visitor questions using the controlled biography document at `app/data/biography.md`. Version 1 uses simple markdown section retrieval and sends only the selected sections to the OpenAI Responses API.

The real biography file is intentionally not committed. The repository includes `app/data/biography.example.md` as a safe placeholder.

## Tech Stack

- Python
- FastAPI
- OpenAI Python SDK
- Pydantic
- Uvicorn
- Railway
- uv

## Local Setup

Install dependencies with uv:

```bash
uv sync
```

Create a local environment file:

```bash
cp .env.example .env
```

Then fill in `OPENAI_API_KEY` and adjust the other values as needed.

Create the private biography file:

```bash
cp app/data/biography.example.md app/data/biography.md
```

Replace the placeholder content in `app/data/biography.md` with verified Andres profile details. Do not commit the real biography file.

## Environment Variables

```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1-mini
ALLOWED_ORIGINS=http://localhost:3000,https://andresblanco.dev
CHAT_API_SECRET=your_server_side_secret_here
API_TITLE=Andres Interview API
API_VERSION=0.1.0
```

`ALLOWED_ORIGINS` accepts a comma-separated list of frontend origins. In production, set this to the portfolio domain that should call `/chat`.

Set `CHAT_API_SECRET` in Railway and in the Next.js server environment. Do not expose it with a public `NEXT_PUBLIC_` prefix.

Generate a local server-side secret with PowerShell:

```powershell
$bytes = New-Object byte[] 32; $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider; $rng.GetBytes($bytes); $rng.Dispose(); "CHAT_API_SECRET=$([Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_'))"
```

Or with Bash when OpenSSL is available:

```bash
echo "CHAT_API_SECRET=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
```

## Run

```bash
uv run uvicorn app.main:app --reload
```

The API docs are available at `http://localhost:8000/docs`.

## Test

```bash
uv run pytest
```

## Main Endpoint Example

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Origin: http://localhost:3000" \
  -H "X-Interview-Secret: your_server_side_secret_here" \
  -d '{"question":"What projects has Andres worked on?"}'
```

Example response:

```json
{
  "answer": "I can't answer that question yet, but I will get back to you!",
  "sources": ["Projects"]
}
```

## Swagger Testing

When `CHAT_API_SECRET` is configured, Swagger requests must include the same secret.

1. Open `/docs`.
2. Click `Authorize`.
3. Enter the value of `CHAT_API_SECRET` from your local `.env`.
4. Run `POST /chat`.

Do not include the header name in the value field. Paste only the secret value.

## Security and Logging

When `CHAT_API_SECRET` is configured, the `/chat` endpoint requires this header:

```http
X-Interview-Secret: your_server_side_secret_here
```

Use this from a server-side Next.js route only. Browser code should call the Next.js route, and the Next.js route should call this FastAPI API with the secret header.

Minimal server-side fetch example:

```ts
await fetch(`${process.env.INTERVIEW_API_URL}/chat`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-Interview-Secret": process.env.CHAT_API_SECRET ?? "",
  },
  body: JSON.stringify({ question }),
});
```

If `CHAT_API_SECRET` is not configured, `/chat` falls back to requiring an `Origin` header that matches `ALLOWED_ORIGINS`. Requests from missing or unapproved origins are rejected before calling OpenAI.

The API also applies a simple in-memory rate limit of 10 chat requests per minute per client IP. This is suitable for a small single-instance Railway deployment. For multiple instances or stricter limits, use a shared rate limiter such as Redis or an API gateway.

Completed chat requests are logged to stdout for Railway logs and to `logs/chat.log` during local runs. Each log includes the client IP, origin, model, question, answer, selected biography sources, and token usage. API keys and chat secrets are never logged.

The local log file is created automatically after the app starts. It is ignored by git.

## Railway Deployment

Railway should use this start command:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Set the same environment variables in Railway. Do not commit real API keys.

Generate a strong `CHAT_API_SECRET`, then set the same value in Railway and in the Next.js server environment. Keep it private.

## Repository Safety Checklist

- `.env` is ignored and must not be committed.
- `app/data/biography.md` is ignored and must not be committed.
- `app/data/biography.example.md` is the public placeholder biography.
- `OPENAI_API_KEY` and `CHAT_API_SECRET` must be set as Railway environment variables.
- Chat logs include questions and answers, so avoid logging private user data from the frontend.
