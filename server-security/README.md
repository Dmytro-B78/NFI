# Server security: Tailscale + Telegram login-уведомления

Цель: SSH (22) и дашборд FreqUI (8080) доступны с ЛЮБОГО IP через Tailscale,
публичный интернет к этим портам доступа не имеет. При каждом успешном входе
(SSH или дашборд) в тот же Telegram-бот, что шлёт алерты по сделкам,
приходит уведомление. Блокировки/подтверждения нет -- это просто видимость.

Все команды ниже выполняются ВРУЧНУЮ пользователем на сервере (vmi3307329).
Claude туда по SSH не заходит и сервисы не перезапускает -- см. правила проекта
(PROJECT_INSTRUCTIONS.md: "Never run SSH commands... on the remote server").

---

## 1. Tailscale (доступ с любого IP)

На сервере:

    curl -fsSL https://tailscale.com/install.sh | sh
    sudo tailscale up

Откроется ссылка для авторизации -- открыть в браузере, привязать к своему аккаунту.

На каждом устройстве, с которого нужен доступ (ноутбук, телефон):
установить клиент (https://tailscale.com/download), войти тем же аккаунтом.

Узнать Tailscale-IP сервера:

    tailscale ip -4

## 2. Закрыть 22 и 8080 от публичного интернета

ВАЖНО: сначала проверить, что Tailscale реально работает (зайти по SSH через
Tailscale-IP из другого места), и только ПОСЛЕ этого сужать ufw -- иначе можно
случайно потерять доступ к серверу.

    sudo ufw allow in on tailscale0
    sudo ufw delete allow from 78.102.237.63 to any port 22
    sudo ufw delete allow from 78.102.237.63 to any port 8080
    sudo ufw status verbose

После этого SSH и дашборд доступны только через Tailscale-сеть, с любого
физического IP, если устройство в твоей Tailscale-сети.

## 3. Скрипты уведомлений

    cd /home/ubuntu/NFI
    git pull
    sudo mkdir -p /opt/nfi-server-security
    sudo cp server-security/notify-ssh-login.sh server-security/frequi-login-notify.sh /opt/nfi-server-security/
    sudo chmod +x /opt/nfi-server-security/*.sh
    sudo cp server-security/.env.example /opt/nfi-server-security/.env
    sudo nano /opt/nfi-server-security/.env

В `.env` вписать TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID -- те же значения, что
уже используются для алертов по сделкам (user_data/config-private.json на
сервере, ключи telegram.token / telegram.chat_id).

## 4. SSH-уведомления (pam_exec)

    sudo nano /etc/pam.d/sshd

Добавить в конец файла одну строку:

    session optional pam_exec.so seteuid /opt/nfi-server-security/notify-ssh-login.sh

Перезапуск sshd не требуется -- PAM подхватывает изменение на следующий логин.

## 5. FreqUI-уведомления (systemd)

    sudo cp server-security/frequi-login-notify.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now frequi-login-notify.service
    sudo systemctl status frequi-login-notify.service

## 6. Проверка

1. Зайти по SSH через Tailscale-IP -- в Telegram должно прийти сообщение
   "SSH login: user=... from=... ...".
2. Зайти в FreqUI (http://<tailscale-ip>:8080) и залогиниться -- должно прийти
   сообщение "FreqUI login: ...".
   Если сообщение НЕ пришло -- посмотреть реальный формат строки лога:

       journalctl -u freqtrade-nfi -n 50 --no-pager | grep -i login

   и подправить условие match в `/opt/nfi-server-security/frequi-login-notify.sh`
   под фактический формат (скорее всего строка вида
   `INFO: <ip>:<port> - "POST /api/v1/token/login HTTP/1.1" 200 OK`, но не
   подтверждено эмпирически -- freqtrade может логировать иначе или не логировать
   HTTP-доступ вовсе, тогда потребуется включить access-логи uvicorn).
3. С обычного (не-Tailscale) IP -- SSH и :8080 должны быть недоступны
   (connection timeout).

## Откат

Если что-то пошло не так и нужен временный доступ по обычному IP:

    sudo ufw allow from <твой текущий IP> to any port 22
    sudo ufw allow from <твой текущий IP> to any port 8080

Отключить уведомления, не трогая Tailscale/firewall:

    sudo systemctl disable --now frequi-login-notify.service
    sudo sed -i '/notify-ssh-login.sh/d' /etc/pam.d/sshd
