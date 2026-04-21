# Cloud Services Update (AWS + OCI) — GitHub Actions

Automates an Excel report on AWS and OCI cloud services every 3 days, pulling **live data from official RSS/Atom feeds**, and emailing it to a recipient at 11 AM UAE.

- **Runs:** every **3 days at 11:00 AM UAE** (07:00 UTC) via GitHub Actions
- **Live sources:** AWS What's New, AWS News Blog, OCI per-service release notes, OCI blog
- **Events:** dates scraped dynamically from official AWS/Oracle event pages — no manual yearly updates needed
- **OCI fallback:** if per-service docs feeds are blocked, automatically falls back to public Oracle RSS feeds
- **Output:** `Cloud_Services_Update_YYYY-MM-DD.xlsx` attached to an email

---

## What's in the report

The Excel file has 4 sheets:

1. **Summary** — item counts, lookback window, links to primary sources
2. **Events** — live and upcoming cloud events (30-day window) with dates, location, and any feed announcements that reference them
3. **AWS Updates** — every AWS announcement from the last 72h, tagged with the likely service name
4. **OCI Updates** — every OCI release-note item from the last 72h, grouped by service

If a feed is quiet in the lookback window, the sheet shows "No new announcements captured in the lookback window" rather than failing.

---

## Repository layout

```
├── .github/
│   └── workflows/
│       └── daily-update.yml   # schedule + runner
├── generate_report.py         # builds the Excel file from live feeds
├── send_email.py              # sends it via Gmail SMTP
├── .gitignore
└── README.md
```

---

## Setup — one-time

### 1) Create the GitHub repo

1. Create a new GitHub repo (public or private).
2. Copy the files above into the repo.
3. Commit and push.

### 2) Create a Gmail App Password

GitHub Actions sends the email through Gmail SMTP. You can't use your regular Gmail password — Google requires an App Password.

1. Enable **2-Step Verification** on the sender account: https://myaccount.google.com/security
2. Go to: https://myaccount.google.com/apppasswords
3. Create a new app password (e.g. "GitHub Actions Cloud Report").
4. Copy the 16-character password.

### 3) Add secrets to your repo

Go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret           | Value                                          |
|------------------|------------------------------------------------|
| `GMAIL_USER`     | Sender Gmail address, e.g. `sender@gmail.com`  |
| `GMAIL_APP_PASS` | The 16-character App Password (no spaces)      |
| `EMAIL_TO`       | Recipient address(es), e.g. `you@example.com`  |

> To send to multiple recipients, set `EMAIL_TO` to a comma-separated list: `a@example.com,b@example.com`

### 4) Test it

1. Go to the **Actions** tab.
2. Click **Cloud Services Update (Every 72h)** → **Run workflow**.
3. ~1 minute later an email should arrive with the Excel attached.

### 5) It now runs every 3 days

Cron is set to `0 7 */3 * *` (UTC) = **11:00 AM UAE (UTC+4)**.

---

## Events — how they work

Event dates are **scraped automatically** from official event pages on each run:

| Event | Source page |
|-------|-------------|
| AWS re:Invent | `aws.amazon.com/events/reinvent/` |
| Oracle AI World | `oracle.com/cloudworld/` |

If a page can't be fetched or no future date is found, a warning is printed and that event is skipped for the run — no crash.

To **add a new event** whose page contains a static date line (e.g. "June 10–12, 2027 \| Austin, TX"), add an entry to `_EVENT_PAGES` in `generate_report.py`:

```python
{"name": "My Event", "provider": "AWS",
 "url": "https://aws.amazon.com/events/my-event/",
 "notes": "Brief description."}
```

Events are shown as **LIVE** (today falls within the dates) or **UPCOMING** (starts within 30 days). Each event block lists any feed items from the lookback window that mention the event by name.

---

## Notes & tweaks

### Change the run frequency / send time
Edit `.github/workflows/daily-update.yml`:
```yaml
- cron: "0 7 */3 * *"   # 07:00 UTC every 3 days = 11:00 AM UAE
```

### Change the lookback window
In `generate_report.py`:
```python
LOOKBACK_HOURS = 72
```
72h covers the 3-day interval. Raise to 96 for extra buffer, or lower for a daily schedule.

### Add or remove tracked AWS services
Edit `AWS_SERVICE_PATTERNS` in `generate_report.py` — a list of `(display_name, regex)`. The regex runs over announcement titles; first match wins.

### Add or remove tracked OCI services
Edit `OCI_SERVICE_FEEDS` — each entry is `(display_name, slug)` where the feed URL is:
`https://docs.oracle.com/en-us/iaas/releasenotes/services/<slug>/feed`

---

## Troubleshooting

**"Username and Password not accepted"** → Use an App Password, not your regular Gmail password (see step 2).

**403 Forbidden on OCI feeds** → The script automatically falls back to public Oracle RSS feeds. No action needed.

**Empty AWS/OCI Updates sheet** → Genuinely quiet period on the feeds, or a temporary feed outage. The Events sheet will still render correctly.

**Scheduled runs don't fire at exactly 11:00** → GitHub cron can be delayed a few minutes under load. Use **Run workflow** for an immediate trigger.

**Email lands in Spam** → Mark as "Not spam" once, or add a filter on the recipient side: From `GMAIL_USER` → Never send to Spam.

**Event not showing** → The event page may not yet have published a future date. It will appear automatically once the page is updated.
