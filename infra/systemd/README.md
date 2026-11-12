# systemd hardening drop-ins

`mangapoisk-umask.conf` is the shared drop-in applied to every
`mangapoisk-*.service` unit. It sets `UMask=0027`, so SQLite WAL/SHM files and
other service-created files are `640` instead of `644`.

Install it on a node:

```bash
for unit in $(systemctl list-unit-files 'mangapoisk-*.service' --no-legend | awk '{print $1}'); do
  install -d -m 755 "/etc/systemd/system/${unit}.d"
  install -m 644 infra/systemd/mangapoisk-umask.conf \
    "/etc/systemd/system/${unit}.d/umask.conf"
done
systemctl daemon-reload
```

Existing processes keep their old umask until restarted. Verify with:

```bash
systemctl show -p UMask mangapoisk-library.service
grep '^Umask:' "/proc/$(systemctl show -p MainPID --value mangapoisk-library.service)/status"
```

Rollback: remove the `umask.conf` drop-ins and run `systemctl daemon-reload`.
See `docs/SECURITY.md` §4 for the full rollback procedure.
