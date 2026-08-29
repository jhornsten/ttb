#!/command/with-contenv bash
# Ensure RPC is reachable on the Docker network; Web UI stays internal-only.
set -euo pipefail
# settings.json defaults already copied; nothing else required for headless use.
true
