# Arris S34 Modem Observability Stack

This project provides full observability for an Arris S34 cable modem using:

- Prometheus for metrics
- Loki for logs
- Promtail for log ingestion
- Grafana for visualization
- Playwright-based scraper for modem data and event logs

It collects DOCSIS signal metrics and the modem Event Log, exposing both time series and searchable logs.

---

## Components

### Metrics
Collected via a custom Python scraper and exported through the Node Exporter textfile collector.

Key metrics include:
- Downstream power per channel
- Downstream SNR per channel
- Correctables and uncorrectables
- Upstream power per channel
- Scrape success and scrape age
- Event log counters and timestamps

### Logs
The modem Event Log is scraped, written to a local log file, and ingested into Loki via Promtail.

Each log entry is structured as JSON and includes:
- Timestamp
- Severity level
- Description
- Source identifier

---

## Directory Layout

```
/usr/bin/
  arris_s34_scrape.py
  arris_s34_write_prom.sh
  promtail

/var/lib/node_exporter/textfile_collector/
  arris_s34.prom

/var/log/
  arris_s34_eventlog.log

/etc/systemd/system/
  arris-s34-exporter.service
  arris-s34-exporter.timer
  promtail.service

/etc/promtail/
  promtail.yml

/etc/loki/
  loki.yml
```

---

## Environment Variables

Set these for the scraper:

```
export MODEM_BASE_URL=https://192.168.100.1
export MODEM_USERNAME=admin
export MODEM_PASSWORD=your_password
```

---

## Prometheus Setup

Node Exporter must be running with the textfile collector enabled:

```
--collector.textfile.directory=/var/lib/node_exporter/textfile_collector
```

Prometheus scrape job example:

```
- job_name: arris_s34_modem
  static_configs:
    - targets: ['localhost:9100']
```

---

## Loki Setup

Loki runs in single-binary mode listening on port 3100.

Ensure:
- WAL is enabled
- Filesystem storage is configured
- No authentication is enabled

Health check:

```
curl http://127.0.0.1:3100/ready
```

---

## Promtail Setup

Promtail tails the modem event log and pushes entries to Loki.

Target file:

```
/var/log/arris_s34_eventlog.log
```

Verify Promtail is running:

```
systemctl status promtail
```

Verify ingestion:

```
curl -G http://127.0.0.1:3100/loki/api/v1/query_range   --data-urlencode 'query={job="arris_s34_eventlog"}'   --data-urlencode "start=$(date -d '5 minutes ago' +%s)000000000"   --data-urlencode "end=$(date +%s)000000000"
```

---

## Grafana Setup

Grafana uses two data sources:
- Prometheus
- Loki

### List Loki Data Sources via API

Use this command to confirm Loki is registered and discover its UID:

```
export GRAFANA_TOKEN='YOUR_TOKEN'

curl -fsS -H "Authorization: Bearer $GRAFANA_TOKEN" http://127.0.0.1:3000/api/datasources \
| python3 - <<'PY'
import sys, json
for ds in json.load(sys.stdin):
    if ds.get("type") == "loki":
        print(ds["name"], "uid="+ds["uid"], "url="+ds.get("url",""))
PY
```

### Explore Logs in Grafana

LogQL example:

```
{job="arris_s34_eventlog"}
```

Filter example:

```
{job="arris_s34_eventlog"} |= "WebGUI"
```

---

## Grafana Dashboards

The dashboard includes:
- Scrape health and age
- DOCSIS signal graphs
- Error rates
- Event counters
- Time since last modem event
- Full log view via Loki Explore

Dashboards can be imported via JSON.

---

## Validation Checklist

- arris_s34.prom updates every minute
- Node Exporter exposes arris_* metrics
- Prometheus queries return values
- Promtail shows active file target
- Loki returns log streams
- Grafana displays metrics and logs

---

## Notes

- Prometheus metrics are numeric summaries
- Loki stores the full raw event text
- This separation keeps metrics efficient and logs searchable
- Event logs are preserved even across modem reboots

---

## License

MIT
