#!/usr/bin/env bash
set -Eeuo pipefail

OUTDIR="/var/lib/node_exporter/textfile_collector"
OUTFILE="${OUTDIR}/arris_s34.prom"
TMPFILE="${OUTFILE}.tmp.$$"

rm -f /var/lib/node_exporter/textfile_collector/arris_s34.prom.tmp.*

python3 /usr/bin/arris_s34_scrape.py > "${TMPFILE}"
mv -f "${TMPFILE}" "${OUTFILE}"
