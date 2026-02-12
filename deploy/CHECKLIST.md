# Deploy Checklist

## App Update
1. `git pull`
2. Install deps if needed: `pip install -r requirements.txt`
3. Run migrations: `python manage.py migrate`
4. Restart service: `sudo systemctl restart renthouse.service`

## Env
- Verify `/opt/rentHouseApp/.env` has:
  - `TELEGRAM_BOT_TOKEN`
  - `ADMIN_TELEGRAM_CHAT_ID`
  - `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGHOST`, `PGPORT`

## Time Zone
1. `sudo timedatectl set-timezone Asia/Phnom_Penh`
2. `timedatectl`

## Monthly Report Timer
1. Copy systemd files:
   - `deploy/systemd/renthouse-monthly-report.service`
   - `deploy/systemd/renthouse-monthly-report.timer`
2. Enable timer:
   - `sudo systemctl daemon-reload`
   - `sudo systemctl enable --now renthouse-monthly-report.timer`
3. Verify:
   - `systemctl list-timers | grep renthouse-monthly-report`

## One-Time Test
```bash
set -a; . /opt/rentHouseApp/.env; set +a
DJANGO_SETTINGS_MODULE=rentHouseApp.settings_prod /opt/rentHouseApp/.venv/bin/python /opt/rentHouseApp/manage.py send_monthly_report --month 2026-01
```

