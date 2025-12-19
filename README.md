Arris S34 Prometheus Exporter and Event Log to Loki

What this is
- A Playwright based scraper that logs into your Arris S34 web UI and exports DOCSIS signal stats to Prometheus via the node_exporter textfile collector.
- The same scraper also pulls the modem Event Log page and writes JSON lines to a local log file.
- Promtail tails that log file and pushes it to Loki.
- Grafana shows both metrics (Prometheus) and raw logs (Loki) on one dashboard.

What you get
Metrics (Prometheus)
- arris_scrape_success
- arris_scrape_timestamp_seconds
- arris_docsis_downstream_power_dbmv{channel="..."}
- arris_docsis_downstream_snr_db{channel="..."}
- arris_docsis_downstream_corrected_total{channel="..."}
- arris_docsis_downstream_uncorrectables_total{channel="..."}
- arris_docsis_upstream_power_dbmv{channel="..."}

Event log metrics (Prometheus)
- arris_eventlog_entries_total{level="..."}
- arris_eventlog_last_event_timestamp_seconds
- arris_eventlog_last_login_timestamp_seconds
- arris_eventlog_webgui_login_success_total
- arris_eventlog_webgui_login_failed_total

Event log lines (Loki)
- JSON lines written to: /var/log/arris_s34_eventlog.log
- Example line:
  {"source":"arris_s34","event":"cmeventlog","ts":"12/18/2025 15:40:44","ts_unix":1766097644,"level":"Notice","desc":"Successful LAN WebGUI login ..."}

Files and paths
- /usr/bin/arris_s34_scrape.py
- /var/lib/node_exporter/textfile_collector/arris_s34.prom
- /var/log/arris_s34_eventlog.log
- /etc/systemd/system/arris-s34-exporter.service
- /etc/arris-s34-exporter.env
- /etc/loki/config.yml
- /etc/promtail/promtail.yml
- /etc/systemd/system/loki.service
- /etc/systemd/system/promtail.service

Prereqs
- Python 3.9+ (Rocky 8/9 works fine)
- node_exporter with textfile collector enabled
- Prometheus scraping node_exporter on this host
- Grafana (already on this box)
- Loki and Promtail (same host is fine)

Python install
1) Install system packages you usually need for Playwright on Rocky:
   sudo dnf install -y python3-pip

2) Install Python deps:
   python3 -m pip install -r requirements.txt

3) Install the Playwright browser once:
   python3 -m playwright install chromium

Environment file
Create /etc/arris-s34-exporter.env
- MODEM_BASE_URL=https://192.168.100.1
- MODEM_USERNAME=admin
- MODEM_PASSWORD=your_password

Permissions:
- sudo chmod 0600 /etc/arris-s34-exporter.env
- sudo chown root:root /etc/arris-s34-exporter.env

Systemd service for the exporter
Example /etc/systemd/system/arris-s34-exporter.service

[Unit]
Description=Arris S34 scraper to node_exporter textfile collector
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=/etc/arris-s34-exporter.env
ExecStart=/usr/bin/arris_s34_scrape.py
User=root
Group=root

Example timer /etc/systemd/system/arris-s34-exporter.timer

[Unit]
Description=Run Arris S34 scraper every minute

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s
AccuracySec=5s
Persistent=true

[Install]
WantedBy=timers.target

Enable:
- sudo systemctl daemon-reload
- sudo systemctl enable --now arris-s34-exporter.timer

node_exporter textfile collector
Ensure node_exporter starts with something like:
- --collector.textfile.directory=/var/lib/node_exporter/textfile_collector

The script should write:
- /var/lib/node_exporter/textfile_collector/arris_s34.prom

Prometheus scrape config
Your Prometheus job should scrape node_exporter:
- targets: ["localhost:9100"] or the host IP
- job name used in your queries: arris_s34_modem

Verify Prometheus sees metrics
- curl -fsS http://127.0.0.1:9100/metrics | grep '^arris_'
- curl -fsS -G http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=arris_scrape_success{job="arris_s34_modem"}'

Loki config
You run Loki as a single binary on this host, listening on 3100.
Keep your existing config, but make sure you have:
- filesystem storage (chunks and index)
- WAL enabled under ingester

Promtail config
Promtail reads /var/log/arris_s34_eventlog.log and pushes to Loki.

Example /etc/promtail/promtail.yml

server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /var/lib/promtail/positions.yml

clients:
  - url: http://127.0.0.1:3100/loki/api/v1/push

scrape_configs:
  - job_name: arris_s34_eventlog
    static_configs:
      - targets: [localhost]
        labels:
          job: arris_s34_eventlog
          host: grafana
          __path__: /var/log/arris_s34_eventlog.log

Promtail systemd unit
Example /etc/systemd/system/promtail.service

[Unit]
Description=Promtail
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/promtail -config.file=/etc/promtail/promtail.yml
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target

Verify Loki has your log lines
1) List labels and jobs:
   curl -fsS http://127.0.0.1:3100/loki/api/v1/labels
   curl -fsS http://127.0.0.1:3100/loki/api/v1/label/job/values

2) Query last 15 minutes:
   curl -fsS -G "http://127.0.0.1:3100/loki/api/v1/query_range" \
     --data-urlencode 'query={filename="/var/log/arris_s34_eventlog.log"}' \
     --data-urlencode "start=$(date -d '15 minutes ago' +%s)000000000" \
     --data-urlencode "end=$(date +%s)000000000" \
     --data-urlencode 'limit=50'

Grafana setup
1) Add Loki datasource (GUI)
- URL: http://127.0.0.1:3100
- Name: loki (or whatever you like)

2) Confirm Grafana sees the Loki datasource via API
This prints Loki datasources with uid and url.

export GRAFANA_TOKEN='YOUR_TOKEN'
curl -fsS -H "Authorization: Bearer $GRAFANA_TOKEN" http://127.0.0.1:3000/api/datasources \
| python3 - <<'PY'
import sys, json
for ds in json.load(sys.stdin):
    if ds.get("type") == "loki":
        print(ds["name"], "uid="+ds["uid"], "url="+ds.get("url",""))
PY

Tip: list all Grafana datasources
export GRAFANA_TOKEN='YOUR_TOKEN'
curl -fsS -H "Authorization: Bearer $GRAFANA_TOKEN" http://127.0.0.1:3000/api/datasources \
| python3 - <<'PY'
import sys, json
for ds in json.load(sys.stdin):
    print(ds["name"], "uid="+ds["uid"], "type="+ds["type"], "url="+ds.get("url",""))
PY

Dashboard
- Import your Arris S34 dashboard JSON.
- For logs, add a Logs panel with datasource Loki and query:
  {job="arris_s34_eventlog"}
- If your log lines are JSON, you can use:
  {job="arris_s34_eventlog"} | json
  Then display fields like ts, level, desc.

Quick smoke test
- Append a test line:
  echo "$(date -Is) TEST arris_s34_eventlog pipeline works" | sudo tee -a /var/log/arris_s34_eventlog.log >/dev/null

- Query it in Loki:
  curl -fsS -G "http://127.0.0.1:3100/loki/api/v1/query_range" \
    --data-urlencode 'query={filename="/var/log/arris_s34_eventlog.log"} |= "TEST arris_s34_eventlog"' \
    --data-urlencode "start=$(date -d '2 minutes ago' +%s)000000000" \
    --data-urlencode "end=$(date +%s)000000000" \
    --data-urlencode 'limit=20'
