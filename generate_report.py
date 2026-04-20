"""
Generates a daily AWS + OCI cloud services update Excel file.

Pulls live announcements from official RSS/Atom feeds:
  - AWS What's New feed
  - AWS News Blog feed
  - OCI per-service release notes feeds
  - OCI cloud-infrastructure blog feed

Also detects live or upcoming cloud events (re:Invent, re:Inforce,
AWS Summits, Oracle AI World, etc.) and produces a dedicated Events sheet.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


UAE_TZ = ZoneInfo("Asia/Dubai")
LOOKBACK_HOURS = 30  # capture ~1 day + cron jitter buffer
HTTP_TIMEOUT = 20
USER_AGENT = "CloudUpdatesBot/1.0 (+github-actions)"


# ---------- FEED CONFIG ----------
AWS_FEEDS = [
    ("AWS What's New", "https://aws.amazon.com/about-aws/whats-new/recent/feed/"),
    ("AWS News Blog",  "https://aws.amazon.com/blogs/aws/feed/"),
]

# Top OCI services with their release-notes feeds.
# Feed URL pattern: https://docs.oracle.com/en-us/iaas/releasenotes/services/<slug>/feed
OCI_SERVICE_FEEDS = [
    ("Compute",                        "compute"),
    ("Object Storage",                 "object-storage"),
    ("Networking",                     "networking"),
    ("Autonomous Database (Shared)",   "autonomous-database-shared"),
    ("Autonomous Database (Dedicated)","autonomous-database-dedicated"),
    ("Base Database",                  "base-database"),
    ("Kubernetes Engine (OKE)",        "kubernetes-engine"),
    ("Functions",                      "functions"),
    ("Generative AI",                  "generative-ai"),
    ("Generative AI Agents",           "generative-ai-agents"),
    ("Data Science",                   "data-science"),
    ("Identity & Access Management",   "identity-and-access-management"),
    ("Monitoring",                     "monitoring"),
    ("Logging",                        "logging"),
    ("FastConnect",                    "fastconnect"),
    ("Load Balancer",                  "load-balancer"),
    ("Database Migration",             "database-migration"),
    ("GoldenGate",                     "goldengate"),
]

OCI_BLOG_FEED = "https://blogs.oracle.com/cloud-infrastructure/rss"


# ---------- EVENT CONFIG ----------
# Edit yearly. Dates inclusive, in the event's local tz (displayed as calendar dates).
EVENTS = [
    # AWS
    {"name": "AWS re:Invent",        "provider": "AWS",    "start": "2026-12-01", "end": "2026-12-05",
     "location": "Las Vegas, USA",
     "notes": "AWS's flagship annual conference with major product launches across compute, AI, data, and security."},
    {"name": "AWS re:Inforce",       "provider": "AWS",    "start": "2026-06-16", "end": "2026-06-18",
     "location": "Philadelphia, USA",
     "notes": "AWS's annual security conference with announcements on identity, detection, data protection, and compliance."},
    {"name": "AWS Summit London",    "provider": "AWS",    "start": "2026-04-22", "end": "2026-04-22",
     "location": "London, UK",
     "notes": "Free AWS Summit with keynotes, breakouts, and regional launches."},
    {"name": "AWS Summit Bengaluru", "provider": "AWS",    "start": "2026-04-23", "end": "2026-04-24",
     "location": "Bengaluru, India",
     "notes": "Free AWS Summit with regional product demos and customer sessions."},
    {"name": "AWS re:MARS",          "provider": "AWS",    "start": "2026-06-01", "end": "2026-06-04",
     "location": "Las Vegas, USA",
     "notes": "Machine learning, automation, robotics, and space conference."},

    # Oracle
    {"name": "Oracle AI World",      "provider": "Oracle", "start": "2026-10-12", "end": "2026-10-16",
     "location": "Las Vegas, USA",
     "notes": "Oracle's flagship annual conference (successor to CloudWorld) focused on AI, database, and cloud."},
    {"name": "Oracle AI World Tour", "provider": "Oracle", "start": "2026-03-01", "end": "2026-11-30",
     "location": "Global (rolling)",
     "notes": "Year-long rolling series of regional AI-focused events by Oracle."},
    {"name": "Oracle Health Summit", "provider": "Oracle", "start": "2026-05-05", "end": "2026-05-07",
     "location": "Nashville, USA",
     "notes": "Annual Oracle Health conference covering EHR, payer, and life sciences."},
]


# ---------- DATA MODEL ----------
@dataclass
class Item:
    title: str
    link: str
    published: datetime   # tz-aware UTC
    summary: str = ""
    source: str = ""
    category: str = ""


# ---------- HTTP / PARSING ----------
def _fetch(url: str) -> bytes:
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
    })
    with urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return r.read()


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _first_sentences(text: str, n: int = 2, max_chars: int = 280) -> str:
    text = _strip_html(text)
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(parts[:n]).strip()
    return (out[: max_chars - 1] + "…") if len(out) > max_chars else out


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_feed(source: str, xml_bytes: bytes) -> list[Item]:
    """Parse RSS 2.0 or Atom 1.0 into Item objects."""
    items: list[Item] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "content": "http://purl.org/rss/1.0/modules/content/",
        "dc": "http://purl.org/dc/elements/1.1/",
    }

    # RSS 2.0
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = _parse_date(it.findtext("pubDate") or it.findtext("dc:date", default="", namespaces=ns))
        summary = it.findtext("description") or it.findtext("content:encoded", default="", namespaces=ns) or ""
        category = (it.findtext("category") or "").strip()
        if title and link and pub:
            items.append(Item(title=title, link=link, published=pub,
                              summary=_first_sentences(summary), source=source, category=category))

    # Atom 1.0
    if not items:
        for entry in root.findall("atom:entry", ns):
            title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
            link_el = entry.find("atom:link[@rel='alternate']", ns) or entry.find("atom:link", ns)
            link = link_el.get("href").strip() if link_el is not None and link_el.get("href") else ""
            pub = _parse_date(
                entry.findtext("atom:updated", default="", namespaces=ns)
                or entry.findtext("atom:published", default="", namespaces=ns)
            )
            summary = (
                entry.findtext("atom:summary", default="", namespaces=ns)
                or entry.findtext("atom:content", default="", namespaces=ns)
                or ""
            )
            cats = [c.get("term", "") for c in entry.findall("atom:category", ns)]
            category = ", ".join([c for c in cats if c])[:80]
            if title and link and pub:
                items.append(Item(title=title, link=link, published=pub,
                                  summary=_first_sentences(summary), source=source, category=category))
    return items


def fetch_feed(source: str, url: str) -> list[Item]:
    try:
        return parse_feed(source, _fetch(url))
    except Exception as e:
        print(f"  [warn] {source} ({url}): {e}", file=sys.stderr)
        return []


# ---------- SERVICE CATEGORIZATION (AWS) ----------
AWS_SERVICE_PATTERNS = [
    ("Amazon EC2",         r"\bamazon ec2\b|\bec2\b"),
    ("AWS Lambda",         r"\blambda\b"),
    ("Amazon S3",          r"\bamazon s3\b|\bs3\b"),
    ("Amazon ECS",         r"\becs\b"),
    ("Amazon EKS",         r"\beks\b"),
    ("Amazon CloudFront",  r"cloudfront"),
    ("Amazon Bedrock",     r"bedrock"),
    ("Amazon CloudWatch",  r"cloudwatch"),
    ("Amazon VPC",         r"\bvpc\b"),
    ("Amazon RDS",         r"\brds\b"),
    ("Amazon DynamoDB",    r"dynamodb"),
    ("Amazon SageMaker",   r"sagemaker"),
    ("Amazon OpenSearch",  r"opensearch"),
    ("Amazon Aurora",      r"aurora"),
    ("Amazon SNS",         r"\bsns\b"),
    ("Amazon SQS",         r"\bsqs\b"),
    ("Amazon Kinesis",     r"kinesis"),
    ("Amazon EMR",         r"\bemr\b"),
    ("AWS IAM",            r"\biam\b|identity and access management"),
    ("AWS Glue",           r"\bglue\b"),
    ("AWS Step Functions", r"step functions"),
    ("Amazon API Gateway", r"api gateway"),
    ("AWS CloudFormation", r"cloudformation"),
    ("AWS Transform",      r"aws transform"),
    ("AWS Security Hub",   r"security hub"),
    ("Amazon GuardDuty",   r"guardduty"),
]

def guess_aws_service(text: str) -> str:
    t = text.lower()
    for name, pat in AWS_SERVICE_PATTERNS:
        if re.search(pat, t):
            return name
    m = re.search(r"\b(Amazon|AWS)\s+([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,2})", text)
    return m.group(0) if m else "AWS"


# ---------- EVENTS ----------
def active_or_upcoming_events(today_uae: datetime, window_days: int = 30) -> list[dict]:
    out = []
    today = today_uae.date()
    for e in EVENTS:
        start = datetime.fromisoformat(e["start"]).date()
        end = datetime.fromisoformat(e["end"]).date()
        if start <= today <= end:
            status, days_to = "LIVE", 0
        elif today < start <= today + timedelta(days=window_days):
            status, days_to = "UPCOMING", (start - today).days
        else:
            continue
        out.append({**e, "status": status, "days_to": days_to,
                    "start_date": start, "end_date": end})
    out.sort(key=lambda x: (x["status"] != "LIVE", x["days_to"]))
    return out


def items_relevant_to_event(items: list[Item], event_name: str) -> list[Item]:
    key = event_name.lower()
    short = re.sub(r"[^a-z0-9]", "", key)
    matches = []
    for it in items:
        hay = (it.title + " " + it.summary).lower()
        if key in hay or short in re.sub(r"[^a-z0-9]", "", hay):
            matches.append(it)
    return matches


# ---------- EXCEL HELPERS ----------
HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=11)
BODY_FONT = Font(name="Arial", size=10)
LINK_FONT = Font(name="Arial", size=10, color="0563C1", underline="single")
TITLE_FONT = Font(name="Arial", bold=True, size=14)
_thin = Side(border_style="thin", color="D0D0D0")
BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def _updates_sheet(ws, rows, title, fill_color, timestamp):
    ws.cell(row=1, column=1).value = title
    ws.cell(row=1, column=1).font = TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=5)
    ws.cell(row=2, column=1).value = timestamp
    ws.cell(row=2, column=1).font = Font(name="Arial", size=9, italic=True, color="666666")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=5)

    headers = ["Service", "Category", "What's Added / Updated", "Source", "Link"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=4, column=col, value=h)
        c.font = HEADER_FONT
        c.fill = PatternFill("solid", start_color=fill_color)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER

    if not rows:
        c = ws.cell(row=5, column=1, value="No new announcements captured in the lookback window.")
        c.font = Font(name="Arial", italic=True, color="888888")
        ws.merge_cells(start_row=5, start_column=1, end_row=5, end_column=5)
    else:
        for i, row in enumerate(rows, start=5):
            for col, val in enumerate(row, 1):
                c = ws.cell(row=i, column=col, value=val)
                c.font = BODY_FONT
                c.alignment = Alignment(vertical="top", wrap_text=True)
                c.border = BORDER
            link_cell = ws.cell(row=i, column=5)
            if row[4]:
                link_cell.hyperlink = row[4]
                link_cell.font = LINK_FONT

    for col, w in {"A": 26, "B": 22, "C": 70, "D": 18, "E": 50}.items():
        ws.column_dimensions[col].width = w
    ws.row_dimensions[4].height = 24
    for r in range(5, 5 + max(len(rows), 1)):
        ws.row_dimensions[r].height = 50
    ws.freeze_panes = "A5"
    ws.sheet_view.showGridLines = False


def _events_sheet(ws, events, aws_items, oci_items, timestamp):
    ws.cell(row=1, column=1).value = "Cloud Events — Daily Summary"
    ws.cell(row=1, column=1).font = TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=5)
    ws.cell(row=2, column=1).value = timestamp
    ws.cell(row=2, column=1).font = Font(name="Arial", size=9, italic=True, color="666666")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=5)

    if not events:
        c = ws.cell(row=4, column=1, value="No live or upcoming events in the next 30 days.")
        c.font = Font(name="Arial", italic=True, color="888888")
        ws.column_dimensions["A"].width = 60
        ws.sheet_view.showGridLines = False
        return

    row = 4
    for e in events:
        status_color = "107C10" if e["status"] == "LIVE" else "8A6D00"
        banner = f"[{e['status']}]   {e['name']}   —   {e['provider']}"
        c = ws.cell(row=row, column=1, value=banner)
        c.font = Font(name="Arial", bold=True, size=12, color="FFFFFF")
        c.fill = PatternFill("solid", start_color=status_color)
        c.alignment = Alignment(vertical="center")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        ws.row_dimensions[row].height = 22
        row += 1

        meta = (f"Dates: {e['start_date']} → {e['end_date']}   |   "
                f"Location: {e['location']}   |   "
                + ("Happening now" if e["status"] == "LIVE" else f"Starts in {e['days_to']} day(s)"))
        mc = ws.cell(row=row, column=1, value=meta)
        mc.font = Font(name="Arial", size=10, italic=True, color="333333")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        row += 1

        nc = ws.cell(row=row, column=1, value=e["notes"])
        nc.font = BODY_FONT
        nc.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        ws.row_dimensions[row].height = 32
        row += 1

        pool = aws_items if e["provider"] == "AWS" else oci_items
        matches = items_relevant_to_event(pool, e["name"])
        hc = ws.cell(row=row, column=1,
                     value=f"Announcements in today's feed referencing this event: {len(matches)}")
        hc.font = Font(name="Arial", bold=True, size=10)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        row += 1

        if matches:
            for m in matches[:10]:
                t = ws.cell(row=row, column=1, value=f"• {m.title}")
                t.font = BODY_FONT
                t.alignment = Alignment(wrap_text=True, vertical="top")
                ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
                lk = ws.cell(row=row, column=5, value="Open")
                lk.hyperlink = m.link
                lk.font = LINK_FONT
                row += 1
        else:
            sk = ws.cell(row=row, column=1, value="(No event-tagged items in today's lookback window.)")
            sk.font = Font(name="Arial", italic=True, color="888888")
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
            row += 1

        row += 1  # spacer

    for col, w in {"A": 40, "B": 18, "C": 30, "D": 30, "E": 14}.items():
        ws.column_dimensions[col].width = w
    ws.sheet_view.showGridLines = False


def _summary_sheet(ws, aws_count, oci_count, event_count, timestamp):
    ws.cell(row=1, column=1).value = "Daily Cloud Services & Offerings Update"
    ws.cell(row=1, column=1).font = Font(name="Arial", bold=True, size=16)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=2)
    ws.cell(row=2, column=1).value = timestamp
    ws.cell(row=2, column=1).font = Font(name="Arial", size=11, italic=True)
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=2)

    info = [
        ("", ""),
        ("Report Contents", ""),
        ("AWS announcements",          f"{aws_count} items in last {LOOKBACK_HOURS}h"),
        ("OCI announcements",          f"{oci_count} items in last {LOOKBACK_HOURS}h"),
        ("Live / upcoming events",     f"{event_count} tracked"),
        ("", ""),
        ("Primary Sources", ""),
        ("AWS What's New",    "https://aws.amazon.com/about-aws/whats-new/recent/feed/"),
        ("AWS News Blog",     "https://aws.amazon.com/blogs/aws/feed/"),
        ("OCI Release Notes", "https://docs.oracle.com/en-us/iaas/releasenotes/"),
        ("OCI Blog",          OCI_BLOG_FEED),
    ]
    for i, (k, v) in enumerate(info, start=3):
        a = ws.cell(row=i, column=1, value=k)
        b = ws.cell(row=i, column=2, value=v)
        if k in ("Report Contents", "Primary Sources"):
            a.font = Font(name="Arial", bold=True, size=11, color="FFFFFF")
            a.fill = PatternFill("solid", start_color="2F5496")
            b.fill = PatternFill("solid", start_color="2F5496")
            ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=2)
        else:
            a.font = Font(name="Arial", bold=True, size=10)
            if str(v).startswith("http"):
                b.hyperlink = v
                b.font = LINK_FONT
            else:
                b.font = BODY_FONT
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 75
    ws.sheet_view.showGridLines = False


# ---------- ORCHESTRATION ----------
def collect_aws(cutoff_utc):
    items = []
    for source, url in AWS_FEEDS:
        items.extend(fetch_feed(source, url))
    items = [i for i in items if i.published >= cutoff_utc]
    items.sort(key=lambda x: x.published, reverse=True)
    return items


def collect_oci(cutoff_utc):
    items = []
    for svc_name, slug in OCI_SERVICE_FEEDS:
        url = f"https://docs.oracle.com/en-us/iaas/releasenotes/services/{slug}/feed"
        fetched = fetch_feed(svc_name, url)
        for it in fetched:
            it.category = svc_name  # tag OCI items with the service they came from
        items.extend(fetched)
    items.extend(fetch_feed("OCI Blog", OCI_BLOG_FEED))
    items = [i for i in items if i.published >= cutoff_utc]
    items.sort(key=lambda x: x.published, reverse=True)
    return items


def aws_rows(items):
    return [(guess_aws_service(it.title), it.category or "",
             it.summary or it.title, it.source, it.link) for it in items]


def oci_rows(items):
    out = []
    for it in items:
        service = it.category or "OCI"
        desc = (it.title + ((". " + it.summary) if it.summary else "")).strip(". ")
        out.append((service, "", desc, it.source, it.link))
    return out


def build_workbook(out_path: str) -> str:
    now_uae = datetime.now(UAE_TZ)
    cutoff_utc = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    timestamp = f"Generated {now_uae.strftime('%A, %d %B %Y, %H:%M %Z')} — lookback {LOOKBACK_HOURS}h"

    print("Fetching AWS feeds…")
    aws_items = collect_aws(cutoff_utc)
    print(f"  {len(aws_items)} AWS items")

    print("Fetching OCI feeds…")
    oci_items = collect_oci(cutoff_utc)
    print(f"  {len(oci_items)} OCI items")

    events = active_or_upcoming_events(now_uae, window_days=30)
    print(f"Events in scope: {len(events)}")

    wb = Workbook()
    summary_ws = wb.active
    summary_ws.title = "Summary"
    _summary_sheet(summary_ws, len(aws_items), len(oci_items), len(events), timestamp)

    _events_sheet(wb.create_sheet("Events"), events, aws_items, oci_items, timestamp)

    _updates_sheet(
        wb.create_sheet("AWS Updates"),
        aws_rows(aws_items),
        f"AWS — Daily Services & Offerings Update ({now_uae.strftime('%d %b %Y')})",
        "FF9900",
        timestamp,
    )
    _updates_sheet(
        wb.create_sheet("OCI Updates"),
        oci_rows(oci_items),
        f"OCI — Daily Services & Offerings Update ({now_uae.strftime('%d %b %Y')})",
        "C74634",
        timestamp,
    )

    wb.save(out_path)
    return out_path


if __name__ == "__main__":
    now_uae = datetime.now(UAE_TZ)
    out = f"Cloud_Services_Update_{now_uae.strftime('%Y-%m-%d')}.xlsx"
    build_workbook(out)
    print(f"Saved: {out}")
