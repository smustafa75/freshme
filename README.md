# Cloud Services Update (AWS + OCI) — GitHub Actions

Automates an Excel report on AWS and OCI cloud services every 3 days, pulling **live data from official RSS/Atom feeds**, and emailing it to a recipient at 11 AM UAE.

- **Runs:** every **3 days at 11:00 AM UAE** (07:00 UTC) via GitHub Actions
- **Live sources:** AWS What's New, AWS News Blog, OCI per-service release notes, OCI blog
- **Events:** detects live/upcoming events (re:Invent, re:Inforce, Oracle AI World, Summits, etc.) and produces a dedicated Events sheet with any announcements that reference them
- **Output:** `Cloud_Services_Update_YYYY-MM-DD.xlsx` attached to an email

---

## What's in the report

The Excel file has 4 sheets:

1. **Summary** — item counts, lookback window, links to primary sources
2. **Events** — live and upcoming cloud events (30-day window) with dates, location, and any announcements from the feed that reference them
3. **AWS Updates** — every AWS announcement from the last 72h, tagged with the likely service name
4. **OCI Updates** — every OCI release-note item from the last 72h, grouped by service

If a feed is quiet in the lookback window, the corresponding sheet shows "No new announcements captured in the lookback window" rather than failing.

---

## Repository layout

```
cloud-updates-automation/
├── .github/
│   └── workflows/
│       └── daily-update.yml       # schedule + runner
├── generate_report.py             # builds the Excel file from live feeds
└── send_email.py                  # sends it via Gmail SMTP
```

> Note: `generate_report.py` and `send_email.py` live at the repo root. The workflow runs `python send_email.py` from the `scripts/` working directory — adjust `working-directory` in the workflow if you move them.

---

## Setup — one-time

### 1) Create the GitHub repo

1. Create a new GitHub repo (private is fine).
2. Copy the files above into the repo using the same folder structure.
3. Commit and push.

### 2) Create a Gmail App Password

GitHub Actions sends the email through Gmail SMTP. You can't use your regular Gmail password — Google requires an App Password.

1. The sender Gmail account must have **2-Step Verification enabled**: https://myaccount.google.com/security
2. Go to: https://myaccount.google.com/apppasswords
3. Create a new app password (e.g. "GitHub Actions Cloud Report").
4. Copy the 16-character password — you'll paste it into GitHub in the next step.

### 3) Add the secrets to your repo

In the GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**. Add three:

| Name             | Value                                      |
|------------------|--------------------------------------------|
| `GMAIL_USER`     | Sender Gmail address, e.g. `you@gmail.com` |
| `GMAIL_APP_PASS` | The 16-character App Password (no spaces)  |
| `EMAIL_TO`       | Recipient address(es)                      |

### 4) Test it

1. Go to the **Actions** tab.
2. Click the **Cloud Services Update (Every 72h)** workflow.
3. Click **Run workflow** → **Run workflow**.
4. ~1 minute later an email should arrive with the Excel attached.

### 5) It now runs every 3 days

Cron is set to `0 7 */3 * *` (UTC) = **11:00 AM UAE**.

---

## Updating events (important, ~once a year)

Events are hard-coded in `generate_report.py` in the `EVENTS` list near the top. Edit this list once a year — or whenever AWS/Oracle announce new dates.

Each event has:

```python
{"name": "AWS re:Invent",  "provider": "AWS",
 "start": "2026-12-01", "end": "2026-12-05",
 "location": "Las Vegas, USA",
 "notes": "AWS's flagship annual conference..."}
```

The script then:
- Marks an event **LIVE** if today falls between `start` and `end`.
- Marks it **UPCOMING** if it starts within the next 30 days.
- Hides it otherwise.

For each event in scope, it searches the feed items for mentions of the event name (and a normalized short form, so "reInvent" and "re:Invent" both match) and attaches the matching items to that event's section.

Want a different window than 30 days? Change `window_days=30` in the `build_workbook` call.

---

## Notes & tweaks

### Change the run frequency / send time
Edit `.github/workflows/daily-update.yml`:
```yaml
- cron: "0 7 */3 * *"   # 07:00 UTC every 3 days = 11:00 AM UAE
```
GitHub cron uses UTC. UAE is UTC+4.

### Change the lookback window
In `generate_report.py`:
```python
LOOKBACK_HOURS = 72
```
72h covers the 3-day run interval with room for cron jitter. Raise it to 96 for extra buffer, or lower it if you switch to a daily schedule.

### Send to multiple recipients
Set `EMAIL_TO` to a comma-separated list, e.g. `a@x.com,b@y.com`. The script passes it straight into the `To:` header; Gmail accepts comma-separated addresses.

### Add or remove tracked services
- **AWS**: edit `AWS_SERVICE_PATTERNS` in `generate_report.py` — a list of `(display_name, regex)`. The regex runs over announcement titles and the first match wins.
- **OCI**: edit `OCI_SERVICE_FEEDS` — each entry is `(display_name, url_slug)` for `https://docs.oracle.com/en-us/iaas/releasenotes/services/<slug>/feed`.

### Cost
- **Public repo:** unlimited GitHub Actions minutes — free.
- **Private repo:** 2,000 free minutes/month. This job uses ~1 min/run → ~10 min/month. Free.

---

## Troubleshooting

**"Username and Password not accepted"** → You're using your regular Gmail password. Use an App Password (step 2).

**403 Forbidden on feed fetches** → Rare, but some CDNs may rate-limit. Retry next run; the script already sends a descriptive User-Agent.

**Empty AWS/OCI Updates sheet** → Genuinely quiet period on the feeds, or a feed outage. The Events sheet will still show in-scope events.

**Scheduled runs don't fire at exactly 11:00** → GitHub cron can be delayed a few minutes under load. The `workflow_dispatch` button always runs immediately for manual triggers.

**Email lands in Spam** → Mark as "Not spam" once, or create a recipient-side filter "From: `GMAIL_USER` → Never send to Spam".

**Event not showing up** → Check that today falls within its `start`–`end` window or within 30 days before `start`. Dates are ISO `YYYY-MM-DD`.
