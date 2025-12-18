#!/usr/bin/env python3
import os
import sys
import time
import re
import json
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

MODEM_URL = os.getenv("MODEM_BASE_URL")
USERNAME = os.getenv("MODEM_USERNAME", "admin")
PASSWORD = os.getenv("MODEM_PASSWORD")

# Write event log rows as JSONL for Loki/Promtail
EVENTLOG_FILE = os.getenv("ARRIS_EVENTLOG_FILE", "/var/log/arris_s34_eventlog.log")
# Prevent writing the same modem table rows every minute
EVENTLOG_STATE_FILE = os.getenv("ARRIS_EVENTLOG_STATE_FILE", "/var/lib/arris_s34_eventlog.state")

if not MODEM_URL:
    print("MODEM_BASE_URL not set", file=sys.stderr)
    sys.exit(1)

if not PASSWORD:
    print("MODEM_PASSWORD not set", file=sys.stderr)
    sys.exit(1)

def num(s):
    if s is None:
        return None
    s = str(s).replace(",", "")
    m = re.search(r"[-+]?\d+(\.\d+)?", s)
    return float(m.group(0)) if m else None

def parse_tables(html):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cols = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
            if cols:
                rows.append(cols)
    return rows

def sectionize(rows):
    sections = {}
    current = None
    for r in rows:
        if len(r) == 1:
            current = r[0]
            sections[current] = {"header": None, "rows": []}
            continue
        if current is None:
            continue
        sec = sections[current]
        if sec["header"] is None:
            sec["header"] = r
        elif len(r) == len(sec["header"]):
            sec["rows"].append(r)
    return sections

def parse_eventlog_rows(html):
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return []

    rows = []
    for tr in table.find_all("tr"):
        cols = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
        if cols:
            rows.append(cols)

    # Drop header row: ['Date Time','Event Level','Description']
    if rows and len(rows[0]) >= 3 and rows[0][0].lower().startswith("date"):
        rows = rows[1:]

    return rows

def parse_event_ts(ts_txt):
    # Matches: 12/18/2025 12:58:32
    try:
        dt = datetime.strptime(ts_txt.strip(), "%m/%d/%Y %H:%M:%S")
        return int(dt.timestamp())
    except Exception:
        return None

def read_last_event_ts():
    try:
        with open(EVENTLOG_STATE_FILE, "r", encoding="utf-8") as f:
            v = f.read().strip()
            return int(v) if v else 0
    except Exception:
        return 0

def write_last_event_ts(ts):
    try:
        os.makedirs(os.path.dirname(EVENTLOG_STATE_FILE), exist_ok=True)
        with open(EVENTLOG_STATE_FILE, "w", encoding="utf-8") as f:
            f.write(str(int(ts)))
    except Exception:
        pass

def append_eventlog_lines(event_rows, last_seen_ts):
    # event_rows are in modem table order (typically newest first)
    # We only append rows with ts > last_seen_ts to avoid duplicates.
    try:
        os.makedirs(os.path.dirname(EVENTLOG_FILE), exist_ok=True)
    except Exception:
        pass

    wrote = 0
    max_ts = last_seen_ts

    # Reverse so we write oldest-to-newest for nicer reading
    for ts_txt, level, desc in reversed(event_rows):
        ts = parse_event_ts(ts_txt)
        if ts is None:
            continue
        if ts <= last_seen_ts:
            continue

        if ts > max_ts:
            max_ts = ts

        line = {
            "source": "arris_s34",
            "event": "cmeventlog",
            "ts": ts_txt,
            "ts_unix": ts,
            "level": (level or "").strip() or "unknown",
            "desc": (desc or "").strip(),
        }

        with open(EVENTLOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        wrote += 1

    if max_ts > last_seen_ts:
        write_last_event_ts(max_ts)

    return wrote

def scrape():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--ignore-certificate-errors"])
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        page.goto(f"{MODEM_URL}/Login.html", wait_until="networkidle")
        page.fill("#loginUsername", USERNAME)
        page.fill("#loginWAP", PASSWORD)
        page.click("#login")
        page.wait_for_timeout(1500)

        page.goto(f"{MODEM_URL}/Cmconnectionstatus.html", wait_until="networkidle")
        status_html = page.content()

        page.goto(f"{MODEM_URL}/Cmeventlog.html", wait_until="networkidle")
        eventlog_html = page.content()

        browser.close()

    # Base scrape metrics
    print("# HELP arris_scrape_success Scrape success")
    print("# TYPE arris_scrape_success gauge")
    print("arris_scrape_success 1")

    print("# HELP arris_scrape_timestamp_seconds Scrape time")
    print("# TYPE arris_scrape_timestamp_seconds gauge")
    print(f"arris_scrape_timestamp_seconds {int(time.time())}")

    # DOCSIS tables
    rows = parse_tables(status_html)
    sections = sectionize(rows)

    ds = sections.get("Downstream Bonded Channels")
    if ds and ds["header"]:
        h = ds["header"]
        idx = {k: h.index(k) for k in h}
        for r in ds["rows"]:
            cid = r[idx["Channel ID"]]
            print(f'arris_docsis_downstream_power_dbmv{{channel="{cid}"}} {num(r[idx["Power"]])}')
            print(f'arris_docsis_downstream_snr_db{{channel="{cid}"}} {num(r[idx["SNR/MER"]])}')
            print(f'arris_docsis_downstream_corrected_total{{channel="{cid}"}} {num(r[idx["Corrected"]])}')
            print(f'arris_docsis_downstream_uncorrectables_total{{channel="{cid}"}} {num(r[idx["Uncorrectables"]])}')

    us = sections.get("Upstream Bonded Channels")
    if us and us["header"]:
        h = us["header"]
        idx = {k: h.index(k) for k in h}
        for r in us["rows"]:
            cid = r[idx["Channel ID"]]
            print(f'arris_docsis_upstream_power_dbmv{{channel="{cid}"}} {num(r[idx["Power"]])}')

    # Event log metrics
    print("# HELP arris_eventlog_entries_total Event log entries by level")
    print("# TYPE arris_eventlog_entries_total gauge")
    print("# HELP arris_eventlog_last_event_timestamp_seconds Last event timestamp")
    print("# TYPE arris_eventlog_last_event_timestamp_seconds gauge")
    print("# HELP arris_eventlog_last_login_timestamp_seconds Last WebGUI login timestamp")
    print("# TYPE arris_eventlog_last_login_timestamp_seconds gauge")
    print("# HELP arris_eventlog_webgui_login_success_total WebGUI login success count")
    print("# TYPE arris_eventlog_webgui_login_success_total gauge")
    print("# HELP arris_eventlog_webgui_login_failed_total WebGUI login failed count")
    print("# TYPE arris_eventlog_webgui_login_failed_total gauge")
    print("# HELP arris_eventlog_new_rows_appended_total New event log rows appended to file during this scrape")
    print("# TYPE arris_eventlog_new_rows_appended_total gauge")

    event_counts = {}
    last_event_ts = 0
    last_login_ts = 0
    login_ok = 0
    login_fail = 0

    ev_rows = parse_eventlog_rows(eventlog_html)

    # Append only new rows to disk for Loki
    last_seen = read_last_event_ts()
    appended = append_eventlog_lines(ev_rows, last_seen)

    for r in ev_rows:
        if len(r) < 3:
            continue
        ts_txt, level, desc = r[0], r[1], r[2]
        ts = parse_event_ts(ts_txt)
        if ts is None:
            continue

        if ts > last_event_ts:
            last_event_ts = ts

        level_key = (level or "").strip() or "unknown"
        event_counts[level_key] = event_counts.get(level_key, 0) + 1

        d = (desc or "").lower()
        if "webgui login" in d:
            if ts > last_login_ts:
                last_login_ts = ts
            if "successful" in d:
                login_ok += 1
            if "failed" in d:
                login_fail += 1

    if not event_counts:
        print('arris_eventlog_entries_total{level="none"} 0')
    else:
        for level, count in sorted(event_counts.items()):
            print(f'arris_eventlog_entries_total{{level="{level}"}} {count}')

    print(f"arris_eventlog_last_event_timestamp_seconds {last_event_ts}")
    print(f"arris_eventlog_last_login_timestamp_seconds {last_login_ts}")
    print(f"arris_eventlog_webgui_login_success_total {login_ok}")
    print(f"arris_eventlog_webgui_login_failed_total {login_fail}")
    print(f"arris_eventlog_new_rows_appended_total {appended}")

if __name__ == "__main__":
    try:
        scrape()
    except Exception as e:
        print("# HELP arris_scrape_success Scrape success")
        print("# TYPE arris_scrape_success gauge")
        print("arris_scrape_success 0")
        print(str(e), file=sys.stderr)
        raise
