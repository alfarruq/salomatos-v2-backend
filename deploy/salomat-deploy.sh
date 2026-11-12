#!/bin/bash
# Runs as root through the `ci` user's forced SSH command (see setup-ci.sh).
# The only input is the target name and a tar.gz on stdin, so the CI key can
# ship a release but cannot open a shell or run anything else on the server.
set -euo pipefail

target="${1:-}"
backend=/srv/salomatos/backend

exec 9>/run/salomat-deploy.lock
flock 9

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

case "$target" in
  backend)
    tar -xz -C "$tmp"
    test -f "$tmp/manage.py"
    # Migrations can't be undone by a redeploy, so take a backup first.
    /usr/local/bin/salomat-backup.sh
    rsync -a --delete --exclude /.venv --exclude /.env --exclude /staticfiles --exclude /.git "$tmp"/ "$backend"/
    chown -R salomat:salomat "$backend"
    runuser -u salomat -- bash -c "cd $backend && .venv/bin/pip install -q -r requirements.txt gunicorn \
      && .venv/bin/python manage.py migrate --noinput && .venv/bin/python manage.py collectstatic --noinput"
    systemctl restart salomat-web salomat-bot
    host=$(sed -n 's/^ALLOWED_HOSTS=\([^,]*\).*/\1/p' "$backend/.env")
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      code=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $host" -H "X-Forwarded-Proto: https" \
        http://127.0.0.1:8000/api/v1/auth/me/ || true)
      [ "$code" = 401 ] && break
      sleep 2
    done
    if [ "$code" != 401 ]; then
      echo "Backend did not come up (HTTP $code). See: journalctl -u salomat-web" >&2
      exit 1
    fi
    ;;
  app | platform)
    tar -xz -C "$tmp"
    test -f "$tmp/index.html"
    rsync -a --delete "$tmp"/ "/var/www/salomatos/$target/"
    ;;
  *)
    echo "Unknown target: $target" >&2
    exit 2
    ;;
esac

echo "Deployed $target"
