# Progress

## 2026-10-26 — Sender name + participant search

**Done**
- Email sender name is now "Department of Artificial Intelligence & Data Science" for test emails and all campaign sends (participant, certificate, bulk). It is hardcoded in `frontend/src/pages/EmailComposePage.tsx` (`SENDER_NAME`). The backend fallback default in `backend/app/core/config.py` matches it.
- Admin → Participants search: the input updates instantly; the server request runs 250 ms after typing stops. The search box no longer disappears while results load. Old results stay visible until new ones arrive.

**Decisions**
- Sender name stays hardcoded in the frontend, by request. It is not driven by the environment variable.
- Old campaigns keep their saved `sender_name`. Retrying them uses the old name. No database records were changed.

**Known issues**
- Search was not exercised in a live browser, only type-checked and code-reviewed.

**Next steps**
- Redeploy on Vercel, send one test email, and check the From line.
