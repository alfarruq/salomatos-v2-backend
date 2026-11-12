#!/bin/bash
# One-time server setup for automatic deploys from GitHub Actions. Run as root:
#   sudo bash /srv/salomatos/backend/deploy/setup-ci.sh
# It prints the two values to store as GitHub secrets in each of the three repos.
set -euo pipefail

install -m 755 -o root -g root "$(dirname "$0")/salomat-deploy.sh" /usr/local/bin/salomat-deploy

id ci >/dev/null 2>&1 || adduser --system --group --shell /bin/bash --home /home/ci ci

echo 'ci ALL=(root) NOPASSWD: /usr/local/bin/salomat-deploy' >/etc/sudoers.d/salomat-ci
chmod 440 /etc/sudoers.d/salomat-ci
visudo -cf /etc/sudoers.d/salomat-ci >/dev/null

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
ssh-keygen -q -t ed25519 -N "" -C github-actions-deploy -f "$tmp/key"

install -d -m 700 -o ci -g ci /home/ci/.ssh
# `restrict` turns off shells, forwarding and ttys; the forced command is all this key can run.
echo "restrict,command=\"sudo /usr/local/bin/salomat-deploy \\\"\$SSH_ORIGINAL_COMMAND\\\"\" $(cat "$tmp/key.pub")" \
  >/home/ci/.ssh/authorized_keys
chown ci:ci /home/ci/.ssh/authorized_keys
chmod 600 /home/ci/.ssh/authorized_keys

ip=$(hostname -I | awk '{print $1}')
echo
echo "===== DEPLOY_KNOWN_HOSTS (one line) ====="
echo "$ip $(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"
echo
echo "===== DEPLOY_SSH_KEY (all lines, BEGIN to END) ====="
cat "$tmp/key"
echo
echo "Store both in GitHub: each repo -> Settings -> Secrets and variables -> Actions."
echo "The private key is not kept on this server; run this script again to issue a new one."
