# Architecture and release boundaries

Version 0.2.0 is a single-user, laptop-only application. It has not been professionally certified, audited or fully exercised on Windows in this build environment. Design structure and tests are supplied so that engineering claims can be checked.

## Modules

- `main.py`: app composition, local Host/Origin boundary, session dependency and existing personal-workspace routes.
- `vault.py`: AES-GCM encrypted records, scrypt passphrase key, versioned schema marker, atomic multi-record writes and consistent encrypted backups. SQLite connections close deterministically. Unsupported future schemas are refused.
- `ai.py`: downloaded local model verification and loopback-only Ollama transport; no cloud fallback.
- `study.py`: validated study commands, course/section scope, encrypted PDF records, referenced Q&A, practice lifecycle and first-answer submission policy.
- `study_core.py`: network-free retrieval, question identity and versioned scoring policy; independently testable.
- `pdf_worker.py`: text extraction in a separate process via memory pipes, with input/page/text/content bounds and a parent timeout. Python cannot enforce a portable Windows memory cap here; a pathological PDF can still exhaust resources. Only trusted study material should be opened.
- `update_engine.py`: independent release signature verification, archive validation, staging, isolated environment preparation, backup, pointer activation and code rollback.
- `updates_api.py`: authenticated update preferences/checks and encrypted backups.
- `browser_core.py`: public-address DNS resolution and pinned TLS transport reused by the updater. It rejects private destinations and does not forward credentials.
- `static/study.js`: study and update UI; external script, escaped output, source inspection, timers and clearing study state on vault lock.

The existing mail, calendar, dictation, task and memory modules remain available. Only code and engineering documentation belong in the GitHub repository. `.gitignore` excludes runtime environments, models, SQLite databases, PDFs, key files, local defaults and release outputs. The release builder uses an explicit source allowlist rather than trusting `.gitignore` to keep secrets out.

## Persistence and migrations

The data directory is outside installed code and versioned updates. Schema 1 preserves the previous encrypted record layout. Adding its schema marker is idempotent and does not rewrite old memories. A regression test opens an old-format vault and checks saved content. Related PDF metadata/pages/original bytes commit in one transaction. Session answers are protected by an in-process mutation lock; run one worker as configured. This is not a multi-user server.

Future incompatible schema changes must add explicit migrations and keep encrypted pre-migration backups. Current releases with a data schema other than 1 are rejected. Code rollback does not automatically rewind user progress. Restore a stopped encrypted database backup separately only when recovery requires it.

## Update trust

`publisher.json` is a trust root shipped with the app. It has no release URL or public key yet. The app never trusts a key merely because a manifest supplies one. The Ed25519 signature covers the version, schema, URL, size and SHA-256 hash. HTTP uses public HTTPS with verified TLS and no redirects/cookies. Archives reject traversal, symlinks, duplicates and runtime/private paths, and enforce size/file-count limits. Signed code is executable and the signing key is consequently highly sensitive. Dependency installation trusts PyPI/package maintainers separately; requirements use bounded compatible ranges, not a complete reproducible hash lock.

Staged updates are installed on next launch. A failed dependency/import check leaves the active pointer unchanged. A failure opening updated code selects previous code; it does not claim a full transaction over every possible application error. The stable launcher and publisher trust live in the original install folder. If that folder is removed, the desktop shortcut cannot recover it automatically.

Automatic checks are optional and occur after unlocking, at most once daily after a successful check. They are separate from the personal-content network toggle and send no study content. No background Windows service, scheduled task, OS security setting change or payment mechanism is installed.

## GitHub

The project repository is [Dirhaya/Local-AI](https://github.com/Dirhaya/Local-AI), created by the owner. It is public; no personal PDFs, vault databases, credentials or signing keys are included. The CI workflow tests Python 3.12 on Ubuntu and Windows and produces a code-only ZIP after passing. A release signing helper is included; keys must be generated and kept outside the repository. Hosting source code does not by itself activate automatic updates. A direct HTTPS release feed and a pinned publisher key still need to be configured.
