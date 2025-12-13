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

scrape_ok = Gauge("modem_scrape_ok", "Last scrape success")

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

def fetch(path):
    r = session.get(
        f"{MODEM_BASE_URL}{path}",
        auth=(MODEM_USERNAME, MODEM_PASSWORD),
        timeout=10
    )
    r.raise_for_status()
    return r.text

def parse_tables(html):
    soup = BeautifulSoup(html, "html.parser")
    return soup.find_all("table")

def scrape():
    html = fetch("/cmSignalData.htm")
    tables = parse_tables(html)

    for table in tables:
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        for row in table.find_all("tr")[1:]:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) != len(headers):
                continue
            rowdata = dict(zip(headers, cols))

            ch = rowdata.get("channel id") or rowdata.get("channel")
            if not ch:
                continue

            if "snr" in rowdata and "power" in rowdata:
                pwr = clean_float(rowdata.get("power"))
                snr = clean_float(rowdata.get("snr"))
                cor = clean_int(rowdata.get("correctables"))
                unc = clean_int(rowdata.get("uncorrectables"))

                if pwr is not None:
                    modem_downstream_power.labels(ch).set(pwr)
                if snr is not None:
                    modem_downstream_snr.labels(ch).set(snr)
                if cor is not None:
                    modem_downstream_correctables.labels(ch).set(cor)
                if unc is not None:
                    modem_downstream_uncorrectables.labels(ch).set(unc)

            if "upstream" in rowdata.get("channel type", "").lower():
                pwr = clean_float(rowdata.get("power"))
                if pwr is not None:
                    modem_upstream_power.labels(ch).set(pwr)

    html = fetch("/cmconnectionstatus.html")
    soup = BeautifulSoup(html, "html.parser")

    for row in soup.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) != 2:
            continue
        key = cols[0].get_text(strip=True).lower()
        val = cols[1].get_text(strip=True)

        if "uptime" in key:
            modem_uptime_str.info({"uptime": val})
            m = re.search(r"(\d+)h:(\d+)m:(\d+)s", val)
            if m:
                secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                modem_uptime.set(secs)

        if "time" in key:
            try:
                ts = int(datetime.strptime(val, "%a %b %d %Y %H:%M:%S").timestamp())
                modem_system_time.set(ts)
            except:
                pass

def main():
    if not MODEM_PASSWORD:
        raise SystemExit("MODEM_PASSWORD not set")

    start_http_server(EXPORTER_PORT)

    while True:
        try:
            scrape()
            scrape_ok.set(1)
        except Exception as e:
            scrape_ok.set(0)
            print(e)
        time.sleep(SCRAPE_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
