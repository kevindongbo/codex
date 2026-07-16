# Private configuration backup

This branch is an isolated backup branch. It is not intended to be merged into
`main` or deployed as application code.

`credentials-20260717.dbenc` is encrypted with AES-256-GCM. The raw 32-byte key
is stored as the GitHub Actions secret `PRIVATE_BACKUP_KEY_B64` and in the
restricted server file `/opt/dongbo/secrets/private-backup.env`.

To decrypt locally, install `cryptography`, expose the key only for the current
process, and run:

```bash
python private-backup/decrypt_backup.py \
  private-backup/credentials-20260717.dbenc \
  /secure/output/private-backup.json
```

The output contains credentials. Keep it outside the repository, restrict its
permissions, and delete it immediately after use.
