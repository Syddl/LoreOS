# Spec: P6 widget

Phase P6 of [the v1 brief](../v1/brief.md). Draft written before P1 started: when P6 starts, re-read it against what P1 to P5 built, then plan.
Sizing: a spend surface open to the public, so every lifecycle step runs and the whole-branch review is by an independent reviewer.

## Summary

A site owner pastes one script tag and visitors can ask a workspace questions from an allowed origin with a publishable key. Unlisted origins are refused, and each key is rate-limited in Postgres before any OpenAI call.
Kill switch: revoking the key stops the widget on every site at once. No environment switch exists, because running without the origin and rate checks would be wrong in every deployment.

## Interfaces

| Interface | Kind | Owner file | Contract |
|---|---|---|---|
| Publishable key | `api_keys` rows, migration | `backend/alembic/versions/` | `kind = 'publishable'`; adds `allowed_origins text[]`, `per_minute int` (default 10), `per_ip_per_minute int` (default 3). Key text `lo_pk_...`, stored in plain text because it is public by design; secret keys stay hashed. |
| `POST /api/widget/ask` | route | `backend/loreos/routes/widget.py` | Header `Authorization: Bearer lo_pk_...`; body `{question}`; response as `POST /api/ask` without internal ids (`n, filename, heading_path, page, text` per citation). |
| `OPTIONS /api/widget/ask` | route | same | CORS preflight: 204 with allow headers for a listed origin; 403 otherwise. |
| `widget.js` | asset | `frontend/widget/` (Vite library build), served at `/widget.js` | `<script src="https://<loreos host>/widget.js" data-key="lo_pk_..." async></script>`, optional `data-title`. Calls back to the origin in its own `src`. |
| `rate_limit` | function | `backend/loreos/ratelimit.py` (P4) | Reused unchanged. |
| Key settings screen | UI | `frontend/` | Create with allowed origins and limits, copy the embed snippet, edit origins, revoke. Owner only. |

## Behaviour

1. The widget mounts a launcher button and a panel inside a shadow root, so the host page's CSS cannot reach it and its CSS cannot leak out; its styles are injected into the shadow root, not the page head.
2. The server answers a widget request only when the key is a live publishable key and the request's `Origin` exactly matches an allowed origin: scheme, host and port. `https://*.example.com` covers subdomains only, not `example.com` itself. A missing or unlisted `Origin` gets 403 with no OpenAI call.
3. Past either limit (per key, or per key and client IP, per minute) the request gets 429 with `Retry-After`, checked before any OpenAI call.
4. CORS headers name the request's origin only when it is listed, with `Vary: Origin`; requests carry no cookies (`credentials: "omit"`).
5. A publishable key reaches `/api/widget/ask` only. On any other route it gets 403.
6. The client IP comes from the proxy header only when the request arrives from a configured trusted proxy (uvicorn's forwarded-allow-ips); otherwise it is the socket address.
7. The worker deletes `rate_limits` rows older than an hour.
8. The snippet the settings screen offers points at the content-hashed build (`/widget.<hash>.js`) with an `integrity` attribute and `crossorigin="anonymous"`, so a tampered file does not run on the owner's site. `/widget.js` stays as an always-latest alias for owners who prefer updates without re-pasting.
9. The README's widget section states the limits honestly: a script outside a browser can forge `Origin`. The origin check stops other sites embedding the widget in browsers, and the rate limit bounds what anyone holding the public key can spend.

## Acceptance checks

| # | Behaviour | Check | Expected | Does NOT exercise |
|---|---|---|---|---|
| 2 | Origin rules | `npm run check:backend`, `tests/test_widget.py` | Listed origin answered (fake LLM); unlisted, missing and a wildcard's bare domain get 403 with no fake call | A real browser |
| 3 | Rate limit (the brief's test) | same file, key with `per_minute = 2` | Third request 429 with `Retry-After`, no fake call; the next window allowed again | Concurrency at scale |
| 4 | CORS | same file | Preflight 204 for listed, 403 for unlisted; `Vary: Origin` present | |
| 5 | Key scope | same file | `lo_pk_` on document routes 403 | |
| 6 | Client IP | same file | Forwarded header ignored from an untrusted peer | |
| 1 | Bundle | `npm run check:frontend` | Widget builds; a vitest mounts it in a shadow root and finds no style in `document.head` | |
| 8 | Snippet integrity | `tests/test_widget.py` | The hashed file's sha384 equals the snippet's `integrity` value | Browser enforcement of SRI |
| 2 | Browser, both ways | Manual: a static page on a listed origin and one on an unlisted origin, against `docker compose up` | Answer with citations on the first; refusal message on the second; ledger row by hand with a screenshot | |

## Kill switch

Revoke the publishable key. No environment key disables the origin or rate checks, and `tests/test_widget.py` pins that.

## Not changing

- Secret keys, sessions and the UI's ask page.
- Retrieval and answering: the widget calls `answer` like every other entry point.
- No uploads, document listing or conversation history in the widget.

## Risks

- React makes the bundle tens of KB gzipped; acceptable for an async script, measured in the plan.
- Wildcard origin matching is easy to get wrong; the tests cover the bare domain and a look-alike suffix (`evilexample.com`).
- A visitor behind a shared IP (an office, a carrier NAT) shares the per-IP limit.
