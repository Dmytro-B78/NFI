#!/usr/bin/env bash
# Sends a Telegram notification on every successful SSH login to this server.
# Deployed as /opt/nfi-server-security/notify-ssh-login.sh
# Invoked by PAM on session open -- see README.md "SSH-уведомления (pam_exec)".
#
# PAM sets these env vars for pam_exec: PAM_TYPE, PAM_USER, PAM_RHOST, PAM_SERVICE.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
fi

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    exit 0
fi

# Only notify when a session actually opens (not on close, not on failed auth --
# PAM only calls session hooks after successful authentication).
if [ "${PAM_TYPE:-}" != "open_session" ]; then
    exit 0
fi

USER_NAME="${PAM_USER:-unknown}"
REMOTE_HOST="${PAM_RHOST:-unknown}"
SERVICE="${PAM_SERVICE:-unknown}"
TS="$(date '+%Y-%m-%d %H:%M:%S %Z')"
HOST_NAME="$(hostname)"

TEXT="SSH login: user=${USER_NAME} from=${REMOTE_HOST} service=${SERVICE} host=${HOST_NAME} time=${TS}"

curl -s -m 10 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${TEXT}" >/dev/null || true

exit 0
