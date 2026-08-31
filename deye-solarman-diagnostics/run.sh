#!/usr/bin/with-contenv bashio
set -euo pipefail

cd /usr/src/app
exec python3 -m deye_solarman_diagnostics
