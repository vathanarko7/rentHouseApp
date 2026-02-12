# Deploy Notes

This folder contains deployment helpers and systemd unit files.

## Monthly Report Timer (systemd)

Files:
- `deploy/systemd/renthouse-monthly-report.service`
- `deploy/systemd/renthouse-monthly-report.timer`

Install on VM:
```bash
sudo cp /opt/rentHouseApp/deploy/systemd/renthouse-monthly-report.service /etc/systemd/system/
sudo cp /opt/rentHouseApp/deploy/systemd/renthouse-monthly-report.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now renthouse-monthly-report.timer
```

Change schedule:
Edit `/etc/systemd/system/renthouse-monthly-report.timer`:
```
OnCalendar=*-*-01 02:00:00
```
Then:
```bash
sudo systemctl daemon-reload
sudo systemctl restart renthouse-monthly-report.timer
systemctl list-timers | grep renthouse-monthly-report
```

Manual run:
```bash
DJANGO_SETTINGS_MODULE=rentHouseApp.settings_prod /opt/rentHouseApp/.venv/bin/python /opt/rentHouseApp/manage.py send_monthly_report --month 2026-01
```

If running in a shell, load `/opt/rentHouseApp/.env` first:
```bash
set -a
. /opt/rentHouseApp/.env
set +a
```

Required env:
- `TELEGRAM_BOT_TOKEN`
- `ADMIN_TELEGRAM_CHAT_ID`
- `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGHOST`, `PGPORT`

