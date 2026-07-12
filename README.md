# Interview

Standalone FastAPI backend for the "Interview Andres" chatbot on Andres Blanco's portfolio website.

The API answers visitor questions using the controlled biography document at `app/data/biography.md`. It uses local hybrid retrieval to select the most relevant biography sections, then sends only those selected sections to the OpenAI Responses API.

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

## Biography Retrieval

The chatbot does not send the full biography to OpenAI on every request. For each `/chat` request, the API:

1. Loads `app/data/biography.md`.
2. Splits the markdown into sections using headings such as `## Experience` and `### Tell me about yourself`.
3. Scores sections locally with hybrid retrieval.
4. Sends only the top selected sections to OpenAI as the biography context.

The retriever combines:

- Exact and near-exact matching for interview-style `###` question headings.
- Optional `Tags:` and `Category:` metadata under section headings.
- BM25-style keyword scoring over section titles, metadata, and content.
- Stable tie-breaking by the section's original order in the biography.

The API currently sends up to 3 selected sections per question. This keeps token usage predictable while allowing the biography file to grow.

Optional section metadata can be added like this:

```md
## Portfolio Project: Web Analytics Data Pipeline
Tags: ETL, BigQuery, analytics engineering, dashboard automation
Category: Projects

Built a reporting pipeline for web analytics and business reporting use cases.
```

`Tags:` and `Category:` help retrieval, but they are not sent to OpenAI in the formatted biography context. Existing sections work without metadata, so tags can be added gradually where retrieval needs more control.

## Environment Variables

```env
APP_ENV=development
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT_SECONDS=15
OPENAI_MAX_RETRIES=1
OPENAI_MAX_OUTPUT_TOKENS=350
ALLOWED_ORIGINS=http://localhost:3000,https://andresblanco.dev
CHAT_API_SECRET=your_server_side_secret_here
TRUSTED_HOSTS=localhost,127.0.0.1,testserver
TRUSTED_PROXY_CIDRS=
CHAT_RATE_LIMIT=10
CHAT_GLOBAL_RATE_LIMIT=60
CHAT_RATE_LIMIT_WINDOW_SECONDS=60
CHAT_RATE_LIMIT_MAX_KEYS=10000
CHAT_MAX_CONCURRENCY=4
CHAT_CONCURRENCY_WAIT_SECONDS=0.25
CHAT_MAX_BODY_BYTES=16384
LOG_CHAT_CONTENT=true
API_TITLE=Andres Interview API
API_VERSION=0.1.0
```

`ALLOWED_ORIGINS` accepts a comma-separated list of frontend origins. In production, set this to the portfolio domain that should call `/chat`.

Set `CHAT_API_SECRET` in Railway and in the Next.js server environment. Do not expose it with a public `NEXT_PUBLIC_` prefix.

Set `APP_ENV=production` on Railway. Production startup fails unless the OpenAI key, a secret of at least 32 characters, explicit allowed origins, explicit trusted hosts, and a non-empty `app/data/biography.md` are present. Set `TRUSTED_HOSTS` to the exact public API hostname plus any Railway hostname used for health checks; never use `*`.

The Railway start command disables Uvicorn proxy-header rewriting so this application can validate forwarding itself. Keep `TRUSTED_PROXY_CIDRS` empty until the current Railway proxy CIDRs have been confirmed, then configure only those CIDRs. Never set it to `0.0.0.0/0` or `::/0`. When it is empty, spoofed `X-Forwarded-For` headers are ignored.

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

`GET /health` is a liveness check. `GET /ready` returns HTTP 200 only when the OpenAI key and real biography are available and all production security requirements pass; it reports booleans without exposing configuration values.

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
  "answer": "I can't answer that question yet, you can reach out to me anytime, my contact details are at the Contact page!",
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

In development, if `CHAT_API_SECRET` is not configured, `/chat` falls back to requiring an `Origin` header that matches `ALLOWED_ORIGINS`. `Origin` is not authentication and production refuses to start without the server-side secret. Browser-shaped requests that include an Origin must pass both secret and origin checks.

The API applies bounded per-client and global sliding-window limits, a concurrency ceiling, and a streaming request-body limit. Expired limiter buckets are removed and the bucket map has a hard capacity. For multiple instances, enforce the primary public limit in the Next.js route or an API gateway; this backend limiter remains defense in depth.

Completed chat requests are logged to stdout for Railway logs and to `logs/chat.log` during local runs. Logs contain the visitor prompt and model answer together with a request ID, keyed visitor hash, status, latency, model, selected biography sources, and token usage. Prompt and answer sizes are already bounded by API validation. JSON encoding prevents multiline log injection, while raw IPs, API keys, and chat secrets remain excluded. Set `LOG_CHAT_CONTENT=false` to disable conversation-content logging without a code change. Configure Railway log access and retention according to the portfolio privacy policy.

Model calls use explicit timeouts, limited retries, an output-token ceiling, `store=False`, and a privacy-preserving safety identifier. The system prompt treats biography and visitor content as untrusted, refuses unsupported claims and role changes, limits answer length, and requests plain text. The backend rejects HTML, Markdown links, unsafe URL schemes, control characters, and oversized model output.

The Next.js frontend must render `answer` as plain text. If Markdown is introduced later, disable raw HTML, sanitize with a strict allowlist, and permit only safe URL schemes. Configure OpenAI project spending alerts and a hard monthly budget in the OpenAI dashboard.

The local log file is created automatically after the app starts. It is ignored by git.

## Railway Deployment

Railway should use this start command:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-proxy-headers
```

Set the same environment variables in Railway. Do not commit real API keys.

Generate a strong `CHAT_API_SECRET`, then set the same value in Railway and in the Next.js server environment. Keep it private.

Set the Railway health-check path to `/ready`. Before enabling `TRUSTED_PROXY_CIDRS`, confirm Railway's current documented proxy network ranges and test that a caller-supplied `X-Forwarded-For` value cannot become the rate-limit identity.

## Repository Safety Checklist

- `.env` is ignored and must not be committed.
- `app/data/biography.md` is ignored and must not be committed.
- `app/data/biography.example.md` is the public placeholder biography.
- `OPENAI_API_KEY` and `CHAT_API_SECRET` must be set as Railway environment variables.
- Production requires a real biography and never falls back to the example file.
- Chat logs include bounded prompts and answers for observability, but omit raw client IPs and secrets.
- CI runs the locked test suite and `pip-audit` on every push and pull request.
