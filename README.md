# Arris S34 Modem Monitoring (Prometheus + Grafana + Loki)

This project provides full observability for an Arris S34 cable modem using Prometheus metrics and Loki logs, visualized in Grafana.

You get:
- DOCSIS signal metrics
- Scrape health and timing
- Parsed modem event counters
- Full searchable modem event logs

---

## Architecture

Components:
- Python scraper (Playwright + BeautifulSoup)
- node_exporter textfile collector
- Prometheus
- Grafana
- Loki
- Promtail

Data flow:
1. Python scraper logs into the Arris S34 WebUI
2. DOCSIS metrics are written to a Prometheus textfile
3. Event log entries are written as structured JSON lines
4. Promtail ships event logs to Loki
5. Grafana visualizes metrics and logs

---

## Requirements

- Linux x86_64
- Python 3.9 or newer
- systemd
- node_exporter
- Prometheus
- Grafana
- Loki
- Promtail

---

## Python Dependencies

Install required Python packages:

pip3 install playwright beautifulsoup4 lxml  
playwright install chromium

---

## Environment Variables

Set these for the scraper:

MODEM_BASE_URL=https://192.168.100.1  
MODEM_USERNAME=admin  
MODEM_PASSWORD=your_password

---

## Python Scraper

Example location:

/usr/bin/arris_s34_scrape.py

Responsibilities:
- Log into modem WebUI
- Scrape DOCSIS status
- Scrape modem event log
- Emit Prometheus metrics
- Write structured event logs

Metrics produced:
- arris_scrape_success
- arris_scrape_timestamp_seconds
- arris_docsis_* metrics
- arris_eventlog_* metrics

Event logs are written to:

/var/log/arris_s34_eventlog.log

---

## node_exporter Textfile Collector

Directory:

/var/lib/node_exporter/textfile_collector

Wrapper script example:

#!/bin/bash
/usr/bin/arris_s34_scrape.py \
  > /var/lib/node_exporter/textfile_collector/arris_s34.prom.tmp \
  && mv /var/lib/node_exporter/textfile_collector/arris_s34.prom.tmp \
        /var/lib/node_exporter/textfile_collector/arris_s34.prom

Always use atomic writes.

---

## systemd Service and Timer

Service file:

/etc/systemd/system/arris-s34-exporter.service

Timer file:

/etc/systemd/system/arris-s34-exporter.timer

Enable:

systemctl daemon-reload  
systemctl enable --now arris-s34-exporter.timer

---

## Prometheus

Prometheus scrapes node_exporter.

Expected labels:
- job=arris_s34_modem
- instance=localhost:9100

---

## Loki

Single-binary Loki configuration is sufficient.

Key features:
- Filesystem storage
- WAL enabled
- Metric aggregation enabled
- No authentication

Listening endpoint:

http://127.0.0.1:3100

---

## Promtail

Promtail is required for log ingestion.

Promtail tails:

/var/log/arris_s34_eventlog.log

Labels added:
- job=arris_s34_eventlog
- level
- host
- filename

Verify:

systemctl status promtail  
curl http://127.0.0.1:9080/targets

---

## Grafana

Data sources:
- Prometheus
- Loki

Dashboard includes:
- Scrape success and age
- DOCSIS downstream and upstream metrics
- Corrected and uncorrected error rates
- Event counters
- Time since last modem event
- Time since last WebGUI login
- Live modem event logs

LogQL example:

{job="arris_s34_eventlog"}

Filter example:

{job="arris_s34_eventlog"} |= "login"

---

## Validation

Metrics check:

curl http://127.0.0.1:9100/metrics | grep arris_

Logs check:

curl -G http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode 'query={job="arris_s34_eventlog"}' \
  --data-urlencode "start=$(date -d '5 minutes ago' +%s)000000000"

---

## Notes

- The Arris S34 WebUI is brittle, headless Chromium is the most reliable method
- Event logs reset on modem reboot
- Metrics and logs are intentionally separated
- Loki provides full forensic visibility

---

## Result

You now have full modem observability:
- Reliable DOCSIS metrics
- Scrape health validation
- Full modem event history
- Searchable logs in Grafana



## Prometheus TSDB cleanup for corrected and uncorrectables

These metrics are counters. If you changed labels or metric names and want to purge old series, you can delete the old series and clean tombstones.

### 1) Confirm the admin API is enabled

```bash
curl -sS http://127.0.0.1:9090/api/v1/status/flags | grep -i admin
```

You should see:
`web.enable-admin-api":"true"`

### 2) Delete the old series

```bash
curl -fsS -X POST "http://127.0.0.1:9090/api/v1/admin/tsdb/delete_series" \
  --data-urlencode 'match[]=arris_docsis_downstream_corrected_total{job="arris_s34_modem",instance="localhost:9100"}' \
  --data-urlencode 'match[]=arris_docsis_downstream_uncorrectables_total{job="arris_s34_modem",instance="localhost:9100"}'
```

### 3) Clean tombstones

```bash
curl -fsS -X POST "http://127.0.0.1:9090/api/v1/admin/tsdb/clean_tombstones"
```

Notes:
- This only deletes series that match the selectors you pass.
- If Prometheus says `admin APIs disabled`, enable the flag and restart Prometheus.

## Prometheus config for /etc/default/prometheus

If your Prometheus systemd unit uses an `EnvironmentFile` and starts Prometheus like this:

`ExecStart=/usr/bin/prometheus $PROMETHEUS_OPTS`

Create or edit `/etc/default/prometheus` to include your normal flags plus the admin API flag.

Example `/etc/default/prometheus`:

```bash
PROMETHEUS_OPTS='--config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/var/lib/prometheus/data --web.console.libraries=/usr/share/prometheus/console_libraries --web.console.templates=/usr/share/prometheus/consoles --web.enable-admin-api=true'
```

Apply changes:

```bash
sudo systemctl daemon-reload
sudo systemctl restart prometheus
sudo systemctl status prometheus --no-pager
```

## Grafana API: list Loki data sources and their UIDs

```bash
export GRAFANA_TOKEN='YOUR_TOKEN'

curl -fsS -H "Authorization: Bearer $GRAFANA_TOKEN" http://127.0.0.1:3000/api/datasources \
| python3 - <<'PY'
import sys, json
for ds in json.load(sys.stdin):
    if ds.get("type") == "loki":
        print(ds["name"], "uid="+ds["uid"], "url="+ds.get("url",""))
PY
```
