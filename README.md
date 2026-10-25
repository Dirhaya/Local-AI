# Sultan Local AI

My own local AI: a laptop study workspace and personal assistant.

**Version 0.2.1 includes a laptop study workspace:** upload encrypted PDFs, ask questions with retrieved page references, generate multiple-choice practice, track chapters and sections, earn XP and view evidence-based readiness levels. See **STUDY-GUIDE.md** for exact scoring rules and limits. **ARCHITECTURE.md** describes storage, module boundaries and update trust. This is engineered source with tests, not a claim of professional certification or complete Windows validation.

Your vault is separate from installed code. The automatic installer now installs the app in a stable user folder and creates a desktop shortcut. Updates support signed staging, backups and code rollback. **Signed update delivery is connected** to the public code-only release feed in your GitHub repository. A pinned publisher key verifies each manifest and archive before installation. Automatic checks are enabled by default for this configured publisher and can be disabled in Updates & backups. The signing key is kept outside the public repository. Source repository: [Dirhaya/Local-AI](https://github.com/Dirhaya/Local-AI). Only code and project documentation belong there; your PDFs and encrypted vault stay on your laptop.

A personal assistant that runs on your Windows computer. A local FastAPI server serves a browser interface, Ollama runs downloaded language models, and optional faster-whisper transcribes audio locally. No invite, subscription or AI API key is required by this app. Model and software licences still apply.

Start with **START-HERE.txt**. This is a runnable first version with source code, not a signed Windows installer or a reproduction of Underdog's proprietary models.

## Windows setup

**Automatic option:** with Ollama already installed, extract the ZIP and double-click **SETUP-EVERYTHING.cmd**. This uses a process-scoped PowerShell execution policy, verifies the official Python installer's signature, installs Python 3.12.10 for your user if necessary, creates the environment, installs speech/app dependencies, downloads a local model and speech model, and launches the app. It preserves other Python installations and does not connect accounts. New vaults receive the installed model/path defaults. Existing vault settings are preserved. It sets the user-level `OLLAMA_NO_CLOUD=1` variable for subsequent Ollama launches; an already running Ollama process must be restarted for that variable to apply. The app still rejects cloud model selections. This installer has not been executed on Windows in the build environment. It requires a 64-bit Intel/AMD Windows PC and several GB for downloads. It currently expects Ollama to be installed, as shown in your screenshot.

Manual option:

1. Install **Python 3.12** and enable **Add Python to PATH**. Python 3.11 also works. Speech dependency compatibility with newer Python versions has not been verified.
2. Install and open [Ollama](https://ollama.com/download/windows).
3. Extract the ZIP, then double-click **Setup-Local-Model-Windows.cmd**. This explicitly downloads `qwen3.5:4b` and sets `OLLAMA_NO_CLOUD=1` for your Windows user. Quit Ollama from the taskbar and reopen it afterwards. The setting affects subsequent Ollama processes, not one already running.
4. Double-click **Start-Windows.cmd**. First launch creates `.venv` and downloads the Python dependencies. Afterwards the launcher opens `http://127.0.0.1:8765`. Keep the terminal window open; Ctrl+C stops the app.
5. Create a vault passphrase of at least 12 characters. In **Settings & privacy**, refresh the local model list, select a downloaded model and save.

Ollama documents `OLLAMA_NO_CLOUD=1` and the need to restart its server in its [official FAQ](https://docs.ollama.com/faq). The app also restricts inference to a numeric loopback address, verifies model metadata and rejects cloud/remote models. It does not sign you into a cloud AI service or fall back to one.

`qwen3.5:4b` is a starting choice, not a hardware guarantee. For limited memory use `ollama pull qwen3.5:2b`. With more memory you can install a larger model and select it in Settings. Performance and answer quality depend on RAM, GPU, model size and input length. Smaller models will make more mistakes. Check the [official model listing](https://ollama.com/library/qwen3.5) for available tags. The app bounds its active context; it does not feed an unlimited chat history into the model.

## Features and their scope

| Feature | Implemented behaviour | What you configure |
|---|---|---|
| Private chat | Local model replies; encrypted history; optional saved memory; separate conversations | Ollama and downloaded local model |
| Meeting notes | Typed notes, local audio transcription, summary, decisions and suggested actions | Speech model for audio; language model for summaries |
| Task tracking | Ready / In progress / Done; edit, due date, delete; explicitly import suggested note actions | Nothing |
| Email | Manually sync recent inbox messages, read, compose and send after review | IMAP/SMTP account credentials; external connections enabled |
| Email search | Search cached subject, sender, recipient and body offline | Sync the messages you want to search first |
| Calendar | Create/edit/delete local events; ICS import/export; read-only CalDAV import | Nothing for local calendar; credentials for CalDAV |
| Privacy controls | Passphrase vault, manual lock, auto-lock, external connections toggle, export and deletion | Save your passphrase safely |
| Dictation | Record in browser or upload audio, transcribe locally, copy/save as a note | Local speech package and model |
| Personal memory | Add, edit, disable and delete facts; global permission plus per-chat opt-in | User-created memories only |
| Browser errands | Public source search for flights, shopping and reservations; read pages; save research; local summary | External connections enabled |

Browser errands are research and manual handoff. They do not log into websites, fill checkout forms, spend money, cancel services or complete reservations. The language model has no action tools. Search snippets can be stale and must not be treated as current prices, live inventory or confirmation of a booking. JavaScript-only pages, bot checks and search rate limits may require opening the source in your own browser. Search failures display a warning and a manual search link; they do not produce fabricated results.

The app uses your browser's microphone recording, **not** the browser's Web Speech recognition service. It does not offer system-wide push-to-talk typing into other apps, automatic speaker identification or automatic extraction of memories. Windows Hello/Face ID, mobile apps, device syncing, end-to-end multi-device sync, native notifications and background email sync are not included.

## Local speech setup

Double-click **Install-Speech-Windows.cmd** after the first app launch. It installs `requirements-speech.txt` and downloads the multilingual `base` model. Copy the folder printed by the script into **Speech model path** in app Settings. Use Edge or Chrome and grant microphone permission to the loopback page.

For a different speech model, run from the app folder:

```powershell
.\.venv\Scripts\python.exe scripts\download_speech.py --model small
```

The available choices are `tiny`, `base`, `small` and `medium`. All are multilingual; larger choices use more memory and CPU. You can set language `en`, `ar` or `auto`. Audio is sent only from the browser to the local server. Transcription loads an existing local model directory with `local_files_only=True`; the running app does not download models. Whisper implementation: [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

The speech engine uses CPU/int8 for a predictable Windows setup. Meeting audio uploads are limited to 100 MB. Split very long meetings into smaller recordings; AI summaries accept at most 40,000 input characters. Transcripts and summaries can contain mistakes, especially with noise, mixed languages and weak models. Action items are suggestions until you explicitly add them to Tasks.

## Email and calendars

See **INTEGRATIONS.md** for detailed account fields. Use an **app password**, where your provider supports it, instead of your main password. OAuth access tokens are also supported for IMAP/SMTP, but this version does not register an OAuth application for you, provide Google/Microsoft login buttons or refresh expired tokens. Outlook and organisational accounts often require administrator-approved OAuth/IMAP/SMTP access. These are provider requirements; local AI does not remove them.

The mail cache syncs the latest 100 inbox messages by default, with a configurable API limit of up to 250. It reads messages without marking them read. Search covers only cached messages, not your entire remote mailbox. Oversized messages may be truncated. HTML mail is converted to inert text and remote images are not loaded. Attachments, sent-folder filing, threading, undo-send, send-later and automatic scheduling are not included. Check Sent mail with your provider if a send fails ambiguously before retrying.

Local calendar events use timezone-aware times. Imported floating/all-day dates default to `Asia/Dubai`; change the import timezone if needed. Recurring ICS events are expanded over a finite window, from 30 days ago to 365 days ahead. Re-import to extend the window. CalDAV requires the exact HTTPS calendar collection URL and performs read-only import. It does not sync local edits back or automatically remove locally cached events when remote ones disappear. Google/Outlook integration is through exported ICS or a provider-supported CalDAV endpoint; native Google/Microsoft calendar OAuth is not included.

## Data and privacy

- The app binds to **127.0.0.1:8765**, uses one local process and blocks cross-origin requests and unexpected Host headers. Mutating requests require an application header. Do not publish it through a tunnel, bind it to `0.0.0.0` or use it as a shared server.
- Vault contents and credentials use **AES-256-GCM**, with a passphrase-derived **scrypt** key. The key and session token are held in process memory while unlocked. The database contains encrypted records plus structural metadata such as record IDs and types. This is record encryption, not whole-disk encryption.
- Default auto-lock is 15 minutes. Lock invalidates the session and releases the key reference. Python, the browser and your OS do not guarantee forensic memory erasure. Lock Windows when leaving your computer.
- **External connections off** blocks app email sync/send, remote calendar import and web research. Chat and local notes/tasks/search still work. This toggle is not a system firewall: installing packages/models and independently running software such as Ollama have their own network behaviour.
- With connections enabled, email goes directly to your configured email provider, calendar requests go to the configured provider, and search queries go to DuckDuckGo. Reading a page contacts its public HTTPS host. Local AI summaries stay on your PC. Public browser research summaries receive only the selected public result data, not private mail or memory.
- No analytics, CDN, remote fonts or cloud model fallback are included in the app. External pages are opened in your own browser only when you choose a link.
- Audio decoding uses a temporary local **plaintext** file, deleted on normal completion or error. Multipart upload handling and the OS can also temporarily spool data. Abrupt process termination, pagefiles, browser memory, backups and SSD snapshots are outside the vault's encryption boundary. Use BitLocker/device encryption for broader disk protection.
- **Export** downloads readable JSON personal content and omits integration credentials. It is not an encrypted backup and does not currently have an in-app restore button. Deletion removes app records; it is not guaranteed physical erasure of disk, backups or snapshots.

Default Windows data folder: `%LOCALAPPDATA%\SultanLocalAI`. Back up `vault.sqlite3` **with the app stopped**, and keep the passphrase separately. Restore an encrypted backup by stopping the app and replacing that database file in the same folder. Lost passphrases cannot be reset to recover data. Do not share this database or your JSON exports. To change the data directory, set `SULTAN_DATA_DIR` before launching.

## Troubleshooting

| Symptom | Action |
|---|---|
| Python/py not found | Install Python 3.12 with PATH enabled, reopen the folder and launcher |
| First package install fails | Check internet access; run the launcher again; inspect the terminal error |
| App opens but cannot chat | Start Ollama; pull a local model; refresh model list; select and save it |
| Chat is slow or runs out of memory | Choose a smaller model; close memory-heavy apps; shorten the prompt |
| Speech not configured | Run speech installer; paste the printed model directory in Settings |
| Microphone denied | Grant microphone access to `http://127.0.0.1:8765` in Edge/Chrome; or upload an audio file |
| Email authentication rejected | Check app-password/OAuth support and organisational IMAP/SMTP policies |
| Research produces no results | Open the provided manual search link; search engines may block automation |
| Port 8765 is busy | Close the other app instance; do not run multiple workers against one unlocked vault |
| App locked during a long operation | Unlock again and retry; an expired session cannot save the result |

## Developer checks

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

The meaningful tests cover vault encryption/authentication, CSRF/Host boundaries, schema validation, chat memory opt-in, summary task imports, email safety, ICS handling, URL/DNS protections and honest web-search failures. See **VERIFICATION.md** for what was actually run in the build environment. Live account tests require your own credentials and have not been performed.

For macOS/Linux, create a Python 3.11/3.12 virtual environment, install `requirements.txt`, install/configure Ollama with cloud features disabled, pull a local model, then run `python run.py`. Optional speech uses the same script. No Docker or Node build is needed. Keep the server on loopback and run a single worker. The software is supplied under the included MIT licence; dependencies and model weights have separate licences.
