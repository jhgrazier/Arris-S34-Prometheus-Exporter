# Arris S34 Prometheus Exporter

Prometheus exporter for the Arris S34 DOCSIS 3.1 cable modem.

This exporter scrapes the Arris S34 web interface and exposes modem signal, channel, and system metrics for Prometheus and Grafana.

Metric names are intentionally kept compatible with the Hitron Coda56 Prometheus Exporter so existing Grafana dashboards continue to work without changes.

---

## Features

- Downstream bonded channel metrics
- Upstream bonded channel metrics
- Downstream OFDM channel metrics
- Modem uptime and system time
- Prometheus metrics endpoint
- Grafana-ready metrics

---

## Exported Metrics

Downstream bonded channels:
- modem_downstream_power
- modem_downstream_snr
- modem_downstream_correctables
- modem_downstream_uncorrectables

Upstream bonded channels:
- modem_upstream_power

Downstream OFDM channels:
- modem_ofdm_power
- modem_ofdm_snr
- modem_ofdm_correctable
- modem_ofdm_uncorrectable

System metrics:
- modem_uptime
- modem_system_time
- modem_uptime_str
- modem_scrape_ok

---

## Requirements

- Python 3.8 or newer
- Network access to the modem at 192.168.100.1
- Arris S34 web interface credentials

Python dependencies:
- requests
- beautifulsoup4
- prometheus_client

---

## Installation

Clone the repository or copy the files manually.

Install Python dependencies:

pip3 install -r requirements.txt

Place the exporter script somewhere permanent, for example:

/usr/bin/arris-s34-exporter.py

Make it executable:

chmod +x /usr/bin/arris-s34-exporter.py

---

## Configuration

The exporter uses environment variables.

Required:
- MODEM_PASSWORD

Optional:
- MODEM_BASE_URL, default https://192.168.100.1
- MODEM_USERNAME, default admin
- EXPORTER_PORT, default 8000
- SCRAPE_INTERVAL_SECONDS, default 30

Example:

export MODEM_BASE_URL=https://192.168.100.1  
export MODEM_USERNAME=admin  
export MODEM_PASSWORD=yourpassword  
export EXPORTER_PORT=8000  

---

## Running Manually

python3 arris-s34-exporter.py

Metrics will be available at:

http://localhost:8000/metrics

---

## Running as a Systemd Service

Copy the service file to:

/etc/systemd/system/arris-s34-exporter.service

Reload systemd and start the service:

systemctl daemon-reload  
systemctl enable --now arris-s34-exporter  

Check status:

systemctl status arris-s34-exporter  

---

## Prometheus Configuration

Add this to your prometheus.yml under scrape_configs:

- job_name: "arris_s34"
  static_configs:
    - targets: ["localhost:8000"]

Reload Prometheus after saving the file.

---

## Grafana

This exporter uses the same metric names as the Hitron Coda56 exporter.

Existing Grafana dashboards should continue to work without modification.

---

## Troubleshooting

If modem_scrape_ok is 0:

- Verify the modem password
- Confirm the modem UI is reachable at https://192.168.100.1
- Confirm the firmware exposes cmSignalData.htm and cmconnectionstatus.html

Manual test:

curl -k -u admin:PASSWORD https://192.168.100.1/cmSignalData.htm  
curl -k -u admin:PASSWORD https://192.168.100.1/cmconnectionstatus.html  

If table headers differ due to firmware changes, the parser may require adjustment.

---

## Notes

- The Arris S34 does not provide a JSON API
- All metrics are scraped from the HTML interface
- Firmware updates may change table formats

---

## License

MIT
