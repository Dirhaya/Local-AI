# Email, calendar and speech setup

Every integration runs on your computer. The encrypted vault stores mail credentials, calendar credentials and cached mail. Internet integrations are disabled until you switch them on in Privacy settings. Downloading model files is a separate setup step.

## Email

Add an account in Mail. This app supports IMAP over TLS on port 993, plus SMTP over implicit TLS on 465 or STARTTLS on 587. TLS certificates are verified. It never falls back to an unencrypted connection.

For Gmail, use `imap.gmail.com` and `smtp.gmail.com`, your complete address as username, and a Google app password when your account allows one. An app password requires Google's account security setup and may be unavailable for managed accounts. Your ordinary account password may be rejected. Google's current instructions are at https://support.google.com/accounts/answer/185833.

For Outlook/Microsoft 365, an ordinary password generally will not work with modern authentication requirements. This version can use an existing OAuth access token with the required IMAP/SMTP delegated scopes via XOAUTH2. It does **not** include Microsoft's sign-in/refresh-token flow; obtaining and renewing the token requires an app registration or another trusted local tool. Organizational administrators may disable these protocols. Use the account settings supplied by your provider, and see Microsoft's protocol instructions at https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth. There is no claim of one-click Outlook setup.

Other providers such as iCloud or a personal mail host can work if they support these protocols and allow app passwords or XOAUTH2. OAuth access tokens expire; replace the saved token when authentication stops working. Blank secrets preserve existing credentials only when the account server/username is unchanged.

Sync explicitly reads the latest 100 inbox messages by default (API limit 250), uses read-only mode, and avoids marking mail as read. It caches at most the first 1 MB of each downloaded message; large messages may be truncated. Attachments are ignored. Search scans the encrypted local cache after decryption in memory and works with internet access switched off. It searches subject, sender, recipients and body. It does not search server folders that were never cached.

Mail is displayed as plain text. Embedded HTML, scripts and tracking images do not execute. Sending requires an explicit review confirmation; the app has no AI tool that sends messages automatically. The SMTP server may save a Sent copy according to its own rules; the app does not append an additional IMAP Sent copy. Attachments, folder management, deletion on the server and automatic background sync are outside this version. If sending fails after submission, check your mailbox before retrying because delivery can be uncertain.

## Calendar

The local calendar works offline. Import `.ics` files downloaded from Google Calendar, Outlook, Apple Calendar or another calendar app. Export writes a standard `.ics` file. Exported files are plaintext; store them where you choose.

Dates with explicit timezones retain their timezone. Floating dates use `Asia/Dubai` unless an IANA timezone is provided to the import API. All-day events retain their dates. Imported UIDs deduplicate repeated imports. Recurring calendars are expanded from 30 days before import through 365 days after import and are exported as individual occurrences. This is a finite snapshot; re-import later to add future dates. Recurrence changes, removals and cancellations are not reconciled automatically; remove obsolete local occurrences manually. If any recurring item is present, that entire calendar's import uses the same date window. Import at most 2,000 expanded events or 10 MB per request.

Optional CalDAV import reads an existing remote calendar collection over public HTTPS on port 443. In the Calendar tab, choose **CalDAV import** and enter the **collection URL**, username and app password. For iCloud or another provider, get the exact CalDAV collection URL from the provider or an existing calendar client's account configuration; a homepage URL is insufficient. This version does not discover calendars from an account root, create remote calendars, use Google/Microsoft OAuth for calendars, or send invitations. It will not forward credentials across redirects. Basic authentication is sent only within verified TLS to the explicit server you provide. Credentials are encrypted locally.

`POST /api/calendar/sync` imports remote events from 30 days ago to 365 days ahead by default. It is a read-only import, not two-way synchronization. Local edits are not uploaded; remote deletions are not applied. Re-importing the same UID/occurrence updates its local copy. Changing the collection URL requires re-entering the password.

## Dictation and meeting recordings

Install `requirements-speech.txt`, download a faster-whisper model with `scripts/download_speech.py`, and set the model folder in Settings. The downloaded folder must contain a converted model's `model.bin`. The speech endpoint passes `local_files_only=True`; it never downloads missing models or calls a cloud transcription service during use.

The default CPU/int8 inference works without a GPU. Larger models improve some languages and accents but use more memory and time; processing speed depends on the computer. A multilingual model is needed for Arabic. Choose language `auto`, `en`, `ar`, or another supported Whisper language code.

Microphone recordings use your browser's MediaRecorder, not the browser's cloud-backed speech-recognition API. Microphone access works on localhost in supported browsers. Uploaded/recorded audio is limited to 100 MB. It is briefly decoded from a private local temporary directory, then removed on success or failure. Transcripts become vault content only when you save a note. Recordings are not retained as encrypted source audio. Process crashes or operating-system failures can leave temporary files; deletion is not a forensic secure erase. Only record conversations you are allowed to record.

## API additions

All routes require an unlocked authenticated vault and the application's mutation-origin guard.

| Route | Body or result |
| --- | --- |
| `GET /api/mail/accounts` | Array of account settings with `has_password` and `has_oauth_token`; no secret values |
| `POST /api/mail/accounts` | `label,email,username,imap_host,imap_port,smtp_host,smtp_port,password,oauth_token`; optional `id` updates an account |
| `POST /api/mail/sync` | `account_id`, optional `limit` from 1 to 250 |
| `GET /api/mail?q=...&account_id=...` | Search cached messages locally |
| `POST /api/mail/send` | `account_id,to,subject,body,confirm:true` |
| `POST /api/calendar/import` | Multipart `file`, optional `timezone` |
| `GET /api/calendar/export` | Download an ICS file |
| `GET /api/calendar/config` | `url,username,has_password` |
| `POST /api/calendar/sync` | `url,username,password`, optional timezone-aware `start,end` and IANA `timezone` |
| `POST /api/transcribe` | Multipart `file`, optional `language` |
