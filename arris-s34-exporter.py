#!/usr/bin/env python3
import os
import sys
import time
import re
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

MODEM_URL = os.getenv("MODEM_BASE_URL")
USERNAME = os.getenv("MODEM_USERNAME", "admin")
PASSWORD = os.getenv("MODEM_PASSWORD")

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

def scrape():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--ignore-certificate-errors"]
        )
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        page.goto(f"{MODEM_URL}/Login.html", wait_until="networkidle")
        page.fill("#loginUsername", USERNAME)
        page.fill("#loginWAP", PASSWORD)
        page.click("#login")
        page.wait_for_timeout(2500)

        page.goto(f"{MODEM_URL}/Cmconnectionstatus.html", wait_until="networkidle")
        html = page.content()
        browser.close()

    rows = parse_tables(html)
    sections = sectionize(rows)

    print("# HELP arris_scrape_success Scrape success")
    print("# TYPE arris_scrape_success gauge")
    print("arris_scrape_success 1")

    print("# HELP arris_scrape_timestamp_seconds Scrape time")
    print("# TYPE arris_scrape_timestamp_seconds gauge")
    print(f"arris_scrape_timestamp_seconds {int(time.time())}")

    ds = sections.get("Downstream Bonded Channels")
    if ds:
        h = ds["header"]
        idx = {k: h.index(k) for k in h}
        for r in ds["rows"]:
            cid = r[idx["Channel ID"]]
            print(f'arris_docsis_downstream_power_dbmv{{channel="{cid}"}} {num(r[idx["Power"]])}')
            print(f'arris_docsis_downstream_snr_db{{channel="{cid}"}} {num(r[idx["SNR/MER"]])}')
            print(f'arris_docsis_downstream_corrected_total{{channel="{cid}"}} {num(r[idx["Corrected"]])}')
            print(f'arris_docsis_downstream_uncorrectables_total{{channel="{cid}"}} {num(r[idx["Uncorrectables"]])}')

    us = sections.get("Upstream Bonded Channels")
    if us:
        h = us["header"]
        idx = {k: h.index(k) for k in h}
        for r in us["rows"]:
            cid = r[idx["Channel ID"]]
            print(f'arris_docsis_upstream_power_dbmv{{channel="{cid}"}} {num(r[idx["Power"]])}')

if __name__ == "__main__":
    try:
        scrape()
    except Exception as e:
        print("# HELP arris_scrape_success Scrape success")
        print("# TYPE arris_scrape_success gauge")
        print("arris_scrape_success 0")
        print(str(e), file=sys.stderr)
