# Proxmox Safe Update

A small Bash tool for supervised Proxmox VE updates. It checks the host, reviews an APT full-upgrade simulation, asks for confirmation, then checks package and guest state after the transaction. It never reboots the host.

## Compatibility

Developed and used on Proxmox VE 9 / Debian 13. The earlier v1.1.0 workflow was used for a real package update on that platform; this v1.1.1 release has additional local mock tests. Proxmox VE 8 and clustered/HA installations have not been validated. This is an in-release maintenance tool, **not a major-version upgrade tool**.

Requires Bash and the standard Proxmox/Debian utilities used by the script, including `apt-get`, `dpkg`, `qm`, `pct`, `pveversion`, and `fuser` (provided by `psmisc`). Missing dependencies cause a stop; the script does not install them.

## Install

Review the script before installing. Keep working backups and arrange a maintenance window for real updates.

```sh
sudo install -o root -g root -m 0750 proxmox-safe-update /usr/local/sbin/proxmox-safe-update
sudo /usr/local/sbin/proxmox-safe-update --version
```

When replacing an existing installation, preserve its previous version first using your normal configuration backup procedure.

## Usage

```sh
# Refresh indexes and inspect the plan; no package installation/removal
sudo /usr/local/sbin/proxmox-safe-update --check

# Review the plan, then confirm an actual full-upgrade
sudo /usr/local/sbin/proxmox-safe-update

# Include complete APT output
sudo /usr/local/sbin/proxmox-safe-update --verbose

proxmox-safe-update --help
```

**`--check` is not strictly read-only:** it refreshes APT indexes and creates temporary diagnostic files. It never installs/removes/upgrades packages. Normal mode accepts `y`, `Y`, or `yes`; any other answer cancels. No answer/closed stdin fails without upgrading. Real upgrades run `apt-get --assume-yes full-upgrade` after confirmation; package maintainer/configuration prompts can still require attention. Use an interactive session and review all removals.

## Checks

- Root privileges, required commands and installed `proxmox-ve` meta-package.
- Active APT/dpkg lock-file users, clean `dpkg --audit`, and root free space.
- APT repository failures, including partial index-fetch errors.
- Simulation counts and explicit package removals.
- Refuse removal of `proxmox-ve`, the running kernel, selected critical host packages or packages marked Essential by dpkg.
- Re-run simulation after confirmation; stop if package actions or summary differ.
- Compare each VM/LXC status before/after and check package database/remaining upgrades.
- Report a newer installed Proxmox kernel or `/run/reboot-required`; no automatic reboot.

Example check output:

```text
UPGRADE PLAN
  Upgrade : 1
  Install : 0
  Remove  : 0
  Held    : 0
  Kernel update detected: NO

SAFETY
  [OK] proxmox-ve preserved
  [OK] No critical Proxmox or Essential packages removed
  [OK] Running kernel preserved
  [OK] Simulation completed successfully

              CHECK COMPLETED - UPDATES AVAILABLE
              No packages were changed.
```

## Free-space thresholds

Defaults: at least 2 GiB **and** 10% available on `/`. Optional environment variables are `MIN_ROOT_FREE_BYTES` and `MIN_ROOT_FREE_PERCENT` (0–99). Both must be nonnegative decimal integers.

```sh
sudo env MIN_ROOT_FREE_BYTES=4294967296 MIN_ROOT_FREE_PERCENT=15 \
  /usr/local/sbin/proxmox-safe-update --check
```

These thresholds are basic checks, not an estimate of transaction space. `/boot`, EFI, separate filesystems and actual download/unpack requirements are not independently sized.

## Limits

- A passing simulation cannot guarantee a successful upgrade or functioning hardware, network, application or guest afterwards. Guest status comparison does not test guest health.
- Lock checks and plan revalidation are point-in-time. There is no atomic lock spanning simulation and installation; another administrator or package process can change state. APT enforces its own transaction locks. Avoid concurrent maintenance.
- The critical package list is conservative but finite. Removing an unlisted package may still be risky. All removals need human review; this tool does not audit repository trust/configuration or automatically repair package failures.
- APT output is parsed with `LC_ALL=C`; unexpected summary formats fail closed. Held packages yield a warning/nonzero result rather than “up to date”.
- “Reboot required” compares the running kernel to `/boot/vmlinuz-*-pve` using version sorting and checks `/run/reboot-required`. It does not resolve pinned kernels or bootloader selection, verify kernel package completeness, or detect every userspace restart requirement.
- Temporary APT/simulation files are removed at exit. There is no persistent audit log or automatic rollback; retain terminal output and inspect APT/dpkg journals as appropriate.
- An upgrade may restart services through package maintainer scripts. The tool does not itself stop/start guests or services, but it cannot prevent package side effects. Interrupting an active APT transaction can leave packages incomplete.
- No notification system, unattended mode, backup execution or recovery automation is included.

Exit codes: `0` successful check, clean completion or explicit cancellation; `1` guardrail/failure/post-check warning; `2` invalid option. Some unexpected command errors retain their command exit status. A successful exit with a reboot notice means the package workflow passed, not that a reboot occurred.

## Development and tests

No Proxmox host, root access or package update is needed for the tests:

```sh
bash -n proxmox-safe-update
shellcheck proxmox-safe-update
python3 -m unittest discover -s tests -v
```

Tests run the workflow with mocked APT/Proxmox/system commands and bypass the root check only in a temporary test copy. They cover check-only behavior, package/removal guards (including architecture suffixes), confirmation, changed plans, package failures, guest changes, kernel notices and verbose logging failure. Production has no root-check bypass option. Mock tests do not establish compatibility with every APT/PVE version.

Repository files: `proxmox-safe-update`, `tests/test_workflow.py`, this README, `LICENSE`, `.gitignore`, `.gitattributes`, and `.github/workflows/checks.yml`.

## License

MIT — see [LICENSE](LICENSE).
