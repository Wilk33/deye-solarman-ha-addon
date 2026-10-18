#!/usr/bin/with-contenv bashio
set -euo pipefail

cd /usr/src/app
exec python3 -m haos_alarm
