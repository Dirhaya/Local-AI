# Verification record

## Version 0.2.0 study/update checks

Completed in this workspace:

- 45 executable Python unit tests: 9 vault/backup/migration tests, 19 retrieval/readiness tests, 5 real-PDF extraction tests and 12 signature/archive/update tests. All passed.
- 26 isolated Node assertions for study/update rendering, escaping, solution withholding, unavailable update feeds, lock-state clearing and select-control preservation. All passed. This is not real-browser verification.
- Python source compilation and JavaScript syntax checks passed.
- The update defaults loader was checked with PowerShell-style UTF-8 BOM input in the previous setup revision.

GitHub CI completed successfully on Ubuntu and Windows for commit 13a07091ce8e020bc0985f40493b706ddc795b96, including the full pytest suite, Node assertions, source compilation and PowerShell script parsing. The first Windows run exposed a separator-normalization bug in release archive validation; it was corrected and the rerun passed. The signed publisher revision has a separate subsequent CI run. Still not exercised: real-browser layout/interaction, local-model question quality, microphone capture, or actually installing software on a personal Windows laptop. The local build workspace itself still lacks FastAPI/pytest/browser binaries; hosted CI provided the complete backend test environment.

The sections below record the earlier version's checks and remaining live acceptance steps.

Build environment: Linux, Python 3.12, Node 24. Windows runtime has not been exercised here.

Passed:

- Six executable vault tests: encrypted persistence, lock behaviour, incorrect passphrase rejection, idle/session expiry, credential-free exports, content deletion/update behaviour and authenticated-ciphertext tamper rejection.
- Fourteen isolated checks against the actual Pydantic payload classes and event date validation: accepted valid inputs, rejected bad statuses, empty chat, invalid settings, naive dates and reversed dates. These do not exercise HTTP routing.
- Python syntax compilation for the app, scripts and test files.
- JavaScript syntax check with `node --check app/static/app.js`.
- HTML checks for duplicate IDs, expected local assets and hidden-state styling. No external script or stylesheet dependencies.
- Eight isolated Node assertions for microphone-permission races after locking or navigation and adaptive activity-touch intervals. These do not replace real browser recording tests.
- Static review of the API/UI contracts, network gating, HTML escaping, recording cleanup and vault lock behaviour.

Not executed:

- The new automatic Windows setup script: PowerShell and Windows are unavailable here. Its installer flags were checked against Python's official Windows documentation. Completed vault/syntax checks remain separate from live installation validation.

- The complete FastAPI/pytest suite. Required dependencies are absent in this environment and package downloads are blocked. The tests are included; run **Check-Windows.cmd** after installation. No full-server startup or integration success is claimed from these partial checks.
- Browser layout and interaction tests. Playwright is installed here but a browser executable is unavailable.
- Real Ollama inference, local speech model loading/microphone capture, live email credentials, remote CalDAV or live search. No messages were sent, accounts connected, bookings made or user credentials used.

## First-run acceptance checks on Windows

1. Install the dependencies and models using START-HERE.txt, then run Check-Windows.cmd. Resolve any failing test before adding important data.
2. Start the app, create a vault, choose a local model and send a short chat. Close/reopen the app and confirm history is restored only after unlocking.
3. Create a task without a due date; change its status and clear an existing date. Add/edit/disable a memory. Check that it appears in chat only with both memory controls enabled.
4. Record a short clip or upload a small audio file. Transcribe it, save as a meeting note, produce a summary and explicitly import its actions.
5. Add a calendar event and export/re-import an ICS file. Verify displayed dates and timezone. Optional CalDAV import should state its read-only scope.
6. Enable external connections. Configure a test email account, manually sync, then disable connections and search the cache. Send only a test message to an address you deliberately enter and review.
7. Enable connections and research a public query. Check source links and manual handoff. A search engine block should produce a clear warning rather than fabricated results.
8. Set auto-lock to one minute, leave the app idle, and confirm the screen clears. Unlock, start an operation, then lock immediately; an old response must not repopulate the locked screen.
9. Confirm app data exports omit account passwords/tokens. Treat the export itself as readable private data. Back up the stopped encrypted database separately if you want a restorable backup.

This record describes completed checks and their limits. It is not a claim that every feature has passed end-to-end testing.
