#!/usr/bin/env python3
import os
import re
import time
import requests
import urllib3
from datetime import datetime
from bs4 import BeautifulSoup
from prometheus_client import start_http_server, Gauge, Info

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MODEM_BASE_URL = os.getenv("MODEM_BASE_URL", "https://192.168.100.1").rstrip("/")
MODEM_USERNAME = os.getenv("MODEM_USERNAME", "admin")
MODEM_PASSWORD = os.getenv("MODEM_PASSWORD", "")
EXPORTER_PORT = int(os.getenv("EXPORTER_PORT", "8000"))
SCRAPE_INTERVAL_SECONDS = int(os.getenv("SCRAPE_INTERVAL_SECONDS", "30"))

session = requests.Session()
session.verify = False
session.headers.update({"User-Agent": "arris-s34-exporter"})

modem_downstream_power = Gauge("modem_downstream_power", "Downstream power dBmV", ["channel"])
modem_downstream_snr = Gauge("modem_downstream_snr", "Downstream SNR dB", ["channel"])
modem_downstream_correctables = Gauge("modem_downstream_correctables", "Downstream correctables", ["channel"])
modem_downstream_uncorrectables = Gauge("modem_downstream_uncorrectables", "Downstream uncorrectables", ["channel"])
modem_upstream_power = Gauge("modem_upstream_power", "Upstream power dBmV", ["channel"])

modem_ofdm_power = Gauge("modem_ofdm_power", "OFDM power dBmV", ["channel"])
modem_ofdm_snr = Gauge("modem_ofdm_snr", "OFDM SNR dB", ["channel"])
modem_ofdm_correctable = Gauge("modem_ofdm_correctable", "OFDM correctables", ["channel"])
modem_ofdm_uncorrectable = Gauge("modem_ofdm_uncorrectable", "OFDM uncorrectables", ["channel"])

modem_uptime = Gauge("modem_uptime", "Uptime seconds")
modem_system_time = Gauge("modem_system_time", "System time epoch")
modem_uptime_str = Info("modem_uptime_str", "Uptime string")
modem_scrape_ok = Gauge("modem_scrape_ok", "Last scrape success (1 ok, 0 fail)")

SIGNAL_PATH_CANDIDATES = [
    "/CmSignalData.htm",
    "/CmSignalData.html",
    "/CmSignalData.asp",
    "/cmSignalData.htm",
    "/cmSignalData.html",
    "/cmsignaldata.htm",
]

CONN_PATH_CANDIDATES = [
    "/Cmconnectionstatus.html",
    "/CmConnectionStatus.html",
    "/cmconnectionstatus.html",
    "/cmConnectionStatus.html",
    "/Cmconnectionstatus.htm",
    "/cmconnectionstatus.htm",
]

def clean_float(val):
    if not val:
        return None
    val = re.sub(r"[^\d\.\-]", "", val)
    try:
        return float(val)
    except:
        return None

def clean_int(val):
    f = clean_float(val)
    return int(f) if f is not None else None

def fetch_any(paths):
    last_err = None
    for path in paths:
        try:
            r = session.get(
                f"{MODEM_BASE_URL}{path}",
                auth=(MODEM_USERNAME, MODEM_PASSWORD),
                timeout=10,
                allow_redirects=True,
            )
            if r.status_code == 200 and r.text and len(r.text) > 200:
                return r.text, path
            last_err = f"{path} -> {r.status_code}"
        except Exception as e:
            last_err = f"{path} -> {e}"
    raise RuntimeError(f"All candidates failed. Last: {last_err}")

def parse_tables(html):
    soup = BeautifulSoup(html, "html.parser")
    return soup, soup.find_all("table")

def table_rows(table):
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        cols = [c.get_text(" ", strip=True) for c in cells]
        if cols and any(x for x in cols):
            rows.append(cols)
    return rows

def header_map(headers):
    return [h.strip().lower() for h in headers]

def scrape_signal_tables(soup):
    # This is intentionally tolerant.
    # It looks for tables that contain "Power" and "SNR" headers for downstream,
    # and tables that contain "Power" plus typical upstream markers.
    for table in soup.find_all("table"):
        rows = table_rows(table)
        if len(rows) < 2:
            continue

        headers = header_map(rows[0])

        # Identify likely downstream bonded table
        if any("snr" in h or "mer" in h for h in headers) and any("power" in h for h in headers):
            for r in rows[1:]:
                if len(r) < len(headers):
                    continue
                d = dict(zip(headers, r))
                ch = d.get("channel id") or d.get("channel") or d.get("id")
                if not ch:
                    continue

                pwr = clean_float(d.get("power") or d.get("power level"))
                snr = clean_float(d.get("snr") or d.get("snr/mer") or d.get("mer"))
                cor = clean_int(d.get("correctables") or d.get("correctable codewords") or d.get("corrected"))
                unc = clean_int(d.get("uncorrectables") or d.get("uncorrectable codewords") or d.get("uncorrected"))

                if pwr is not None:
                    modem_downstream_power.labels(str(ch)).set(pwr)
                if snr is not None:
                    modem_downstream_snr.labels(str(ch)).set(snr)
                if cor is not None:
                    modem_downstream_correctables.labels(str(ch)).set(cor)
                if unc is not None:
                    modem_downstream_uncorrectables.labels(str(ch)).set(unc)

        # Identify likely upstream bonded table
        if any("upstream" in h for h in headers) or any("symbol" in h for h in headers):
            for r in rows[1:]:
                if len(r) < len(headers):
                    continue
                d = dict(zip(headers, r))
                ch = d.get("channel id") or d.get("channel") or d.get("id")
                if not ch:
                    continue
                pwr = clean_float(d.get("power") or d.get("power level"))
                if pwr is not None:
                    modem_upstream_power.labels(str(ch)).set(pwr)

        # Identify likely OFDM table
        if any("ofdm" in h for h in headers) or any("plc" in h for h in headers):
            for r in rows[1:]:
                if len(r) < len(headers):
                    continue
                d = dict(zip(headers, r))
                ch = d.get("channel id") or d.get("channel") or d.get("profile id") or d.get("id")
                if not ch:
                    continue

                pwr = clean_float(d.get("power") or d.get("plc power") or d.get("rx power"))
                snr = clean_float(d.get("snr") or d.get("snr/mer") or d.get("mer"))
                cor = clean_int(d.get("correctable") or d.get("correctable codewords") or d.get("correctables"))
                unc = clean_int(d.get("uncorrectable") or d.get("uncorrectable codewords") or d.get("uncorrectables"))

                if pwr is not None:
                    modem_ofdm_power.labels(str(ch)).set(pwr)
                if snr is not None:
                    modem_ofdm_snr.labels(str(ch)).set(snr)
                if cor is not None:
                    modem_ofdm_correctable.labels(str(ch)).set(cor)
                if unc is not None:
                    modem_ofdm_uncorrectable.labels(str(ch)).set(unc)

def scrape_conn_info(soup):
    # Pull uptime and system time from 2-col tables.
    for tr in soup.find_all("tr"):
        tds = tr.find_all(["td", "th"])
        if len(tds) < 2:
            continue
        k = tds[0].get_text(" ", strip=True).lower()
        v = tds[1].get_text(" ", strip=True)

        if "uptime" in k:
            modem_uptime_str.info({"uptime": v})
            m = re.search(r"(\d+)\s*h[: ](\d+)\s*m[: ](\d+)\s*s", v, re.IGNORECASE)
            if m:
                secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                modem_uptime.set(secs)

        if "time" in k:
            # Try common Arris format, tolerate failures
            try:
                ts = int(datetime.strptime(v, "%a %b %d %Y %H:%M:%S").timestamp())
                modem_system_time.set(ts)
            except:
                pass

def scrape():
    if not MODEM_PASSWORD:
        raise RuntimeError("MODEM_PASSWORD not set")

    sig_html, sig_path = fetch_any(SIGNAL_PATH_CANDIDATES)
    sig_soup, _ = parse_tables(sig_html)
    scrape_signal_tables(sig_soup)

    conn_html, conn_path = fetch_any(CONN_PATH_CANDIDATES)
    conn_soup, _ = parse_tables(conn_html)
    scrape_conn_info(conn_soup)

def main():
    start_http_server(EXPORTER_PORT)
    while True:
        try:
            scrape()
            modem_scrape_ok.set(1)
        except Exception as e:
            modem_scrape_ok.set(0)
            print(e)
        time.sleep(SCRAPE_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
