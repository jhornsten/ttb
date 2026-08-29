#!/command/with-contenv bash
# Install Deluge defaults on first boot; hash web password from DELUGE_PASSWORD.
set -euo pipefail

export PASSWORD="${DELUGE_PASSWORD:-ttb}"

if [[ ! -f /config/core.conf ]]; then
  echo "[ttb] installing default core.conf"
  cp /defaults/core.conf /config/core.conf
fi

if [[ ! -f /config/web.conf ]]; then
  echo "[ttb] installing default web.conf"
  # Deluge web auth: sha1(utf8(salt) + utf8(password))
  read -r SALT HASH < <(python3 -c "
import hashlib, os, secrets
salt = secrets.token_hex(20)
s = hashlib.sha1()
s.update(salt.encode('utf-8'))
s.update(os.environ['PASSWORD'].encode('utf-8'))
print(salt, s.hexdigest())
")
  sed -e "s/__PWD_SALT__/${SALT}/" -e "s/__PWD_SHA1__/${HASH}/" \
    /defaults/web.conf.template > /config/web.conf
fi

if [[ ! -f /config/auth ]]; then
  echo "[ttb] installing default auth"
  echo "localclient:${PASSWORD}:10" > /config/auth
fi
