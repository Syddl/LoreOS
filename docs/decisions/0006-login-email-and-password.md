---
id: 0006
title: The UI logs in with email and password
date: 2026-10-11
status: accepted
superseded_by:
---

# The UI logs in with email and password

## Decision

People log in to the web UI with an email address and a password. This settles the brief's open question "Login method for the UI (decided in P4)".
- Passwords are hashed with argon2id through `argon2-cffi` (MIT) and need at least 12 characters.
- A session is a 14-day `HttpOnly` cookie; the database keeps only its hash.
- New members join through single-use invite links that an owner shares by hand. LoreOS sends no email.
- A forgotten password is reset by the operator with `python -m loreos.admin reset-password <email>`.

## Why

It is the smallest login that works self-hosted with no outside service.
- **Passkeys** (py_webauthn) need more code, are hard to test without a browser, and would still need the CLI reset for a lost device.
- **Magic links** need email sending, which the brief leaves out.
- **OIDC and SSO** need an identity provider, also out of scope.
- **Stdlib `hashlib.scrypt`** avoids one dependency, but leaves the parameters and the stored encoding to us. argon2-cffi's defaults follow current guidance.

## Kill switch

None. Running without login would be wrong in every deployment (P4 spec, "Kill switch").

## Reopen only if

- A deployment needs SSO, or email sending enters scope.
- argon2-cffi stops being maintained.
