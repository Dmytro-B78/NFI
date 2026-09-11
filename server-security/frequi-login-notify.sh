#!/usr/bin/env bash
# Watches the freqtrade-nfi journal for successful FreqUI dashboard logins
# and sends a Telegram notification for each one.
# Deployed as /opt/nfi-server-security/frequi-login-notify.sh
# Run persistently via systemd unit frequi-login-notify.service (see README.md).
#
# NOTE: the exact access-log line format depends on freqtrade's uvicorn logging.
# Verify after first deploy (README.md "Проверка") -- if no notification arrives
# on a real login, check `journalctl -u freqtrade-nfi -n 50 --no-pager | grep -i login`
# and adjust the match condition below to the actual format.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
fi

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    echo "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set in ${ENV_FILE}, exiting" >&2
    exit 1
fi

notify() {
    local line="$1"
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S %Z')"
    curl -s -m 10 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        --data-urlencode "text=FreqUI login: ${line} | host=$(hostname) | time=${ts}" >/dev/null || true
}

# -n 0: don't replay old history on start, only react to new lines from now on.
journalctl -u freqtrade-nfi -f -n 0 --no-pager | while IFS= read -r line; do
    if [[ "$line" == *"POST /api/v1/token/login"* ]] && [[ "$line" == *" 200 "* ]]; then
        notify "$line"
    fi
done
