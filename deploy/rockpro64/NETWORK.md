# DanceMate ROCKPro64 — Network Baseline

Surveyed on the live board 2026-09-03. Nothing in this file is a secret; the
SSH credential and the PostgreSQL password live only in `.env` (mode 600) and
`/opt/dancemate/docker/database/.env`.

## Summary

| | |
|---|---|
| Hostname | `rockpro64` |
| Primary interface | `end0` (wired Ethernet) — DanceMate staging path |
| Secondary interface | `wlan0` (WiFi) — temporary internet uplink |
| DanceMate port | `8080`, published on `192.168.1.100` only |
| SSH | `ssh root@192.168.1.100` over `end0` |
| Docker network | `dancemate-net` (external bridge, `172.18.0.0/16`) |
| Policy | LAN only. No WAN port forwarding, no DMZ, no UPnP, no public reverse proxy |

## Interfaces as measured

### end0 — primary, wired

| | |
|---|---|
| MAC | `16:F5:F3:EF:44:96` |
| MAC assignment | `addr_assign_type = 0` (permanent, from hardware) |
| Address | `192.168.1.100/24`, **static** |
| Gateway | none on this segment |
| DNS | `8.8.8.8` |
| Managed by | NetworkManager, connection profile `static-end0` (`ipv4.method: manual`) |

The MAC's first octet has the locally-administered bit set, which is normal for
RK3399 boards that derive the address from the SoC ID rather than a vendor
EEPROM. It is stable: the kernel reports it as permanent, and the development
PC's neighbour entry for `192.168.1.100` stayed `16-F5-F3-EF-44-96` across both
host reboots during the v0.74 acceptance.

### wlan0 — secondary, WiFi

| | |
|---|---|
| MAC | `AC:83:F3:E6:1A:2A` |
| Address | `10.0.0.55/16`, DHCP |
| Gateway | `10.0.0.1` — **carries the current default route** (metric 1024) |
| DNS | `192.168.1.224`, `192.168.1.191` |
| Managed by | `wpa_supplicant-wlan0.service` + systemd-networkd (`/etc/systemd/network/25-wlan0.network`) |

NetworkManager reports `wlan0` as `unavailable` on purpose: wpa_supplicant owns
it. Both services are `enabled` and survive a reboot.

## Current topology

```
   development PC                      ROCKPro64
   192.168.1.101/24  <--- direct --->  192.168.1.100/24  (end0, static)
                       Ethernet             |
                     no gateway             |  default route
                                            v
                                    wlan0 10.0.0.55/16 --> 10.0.0.1 --> internet
```

`192.168.1.0/24` is a **gateway-less direct link between the development PC and
the board**, not a router LAN. Outbound internet (git, container images, future
source APIs) travels over WiFi.

## Addressing decision

**Host static IP on `end0` — kept.**

DHCP reservation on the router is the better long-term answer and stays the
recommendation, but it is **not applicable today**: `192.168.1.0/24` has no
router and no DHCP server on it at all, so there is nothing to reserve from.
A static address is what makes SSH survive a reboot on this segment, and it did
so twice during the v0.74 acceptance.

No network configuration was changed while establishing this baseline.

### When the board moves to the real router

Ask the router for a DHCP reservation and then switch `end0` to DHCP:

| Field | Value |
|---|---|
| Interface | `end0` |
| MAC | `16:F5:F3:EF:44:96` |
| Requested IP | keep `192.168.1.100` if the router's subnet allows, otherwise any stable address |
| Hostname | `rockpro64` |

Then, in order:

1. `nmcli connection modify static-end0 ipv4.method auto ipv4.addresses "" ipv4.dns ""`
2. update `DANCEMATE_BIND_ADDRESS` in `.env` to the new address
3. `scripts/start-server.sh` (re-publishes the port on the new interface address)
4. `scripts/check-server.sh` — expect six PASS
5. reboot and re-verify

Once the wired LAN provides internet, disable the temporary WiFi uplink:

```bash
sudo systemctl disable --now wpa_supplicant-wlan0.service
```

Do **not** do this before the wired path has a gateway: WiFi is currently the
only route out.

## Two addresses, not one

| Variable | Meaning | Value on this board |
|---|---|---|
| `DANCEMATE_BIND_ADDRESS` | host interface Docker publishes the port on | `192.168.1.100` |
| `DANCEMATE_HOST` | address the server listens on **inside** the container | `0.0.0.0` (pinned by both compose files) |

A container has no LAN address of its own. Putting the board's IP in
`DANCEMATE_HOST` makes uvicorn fail with *could not bind on any address*. The
health scripts derive their probe host from `DANCEMATE_BIND_ADDRESS`, because
loopback stops listening once the published binding is narrowed.

Verified exposure:

```
LISTEN  192.168.1.100:8080     DanceMate runtime   (LAN, wired only)
LISTEN  0.0.0.0:80             caddy               (pre-existing)
LISTEN  0.0.0.0:22             sshd
```

`8080` answers on `192.168.1.100` and **not** on `10.0.0.55` (WiFi) or
`127.0.0.1`. PostgreSQL publishes no host port at all — it is reachable only
inside `dancemate-net`.

## Warm reboot can hang — power cycle is the recovery

Observed 2026-09-03. `systemctl reboot` shut down cleanly and the kernel
started again (journal records `Booting Linux`, wtmp records the boot), but the
board then froze before networking came up and stayed unreachable on both
`end0` and `wlan0` for ~27 minutes until it was power cycled.

It is a board-level warm-reset problem, not a DanceMate one:

- the filesystem was `clean` afterwards, no fsck, no I/O or mmc errors
- every DanceMate record survived: 18 source items, 5 collection runs,
  15 live Event Candidates, provider quota, all Korean text
- on the power-cycled boot all four containers were healthy within ~26s with
  no manual start, and a live collection ran immediately afterwards

Three earlier `systemctl reboot` cycles on this board (two during the v0.74
acceptance, one during v0.75) recovered in about 15 seconds, so this is
intermittent rather than systematic — consistent with the RK3399 warm-reset
behaviour ROCKPro64 boards are known for.

**Operationally**: if the board does not answer within ~2 minutes of a reboot,
power cycle it. Nothing needs repairing afterwards. For unattended operation,
prefer `poweroff` + power-on, or attach a serial console (the board exposes
`ttyS2`) so a hung boot can be diagnosed rather than guessed at.

The `brcmfmac4359-sdio.pine64,rockpro64-v2.1.bin ... error -2` lines in dmesg
are **not** a fault: the kernel tries board-specific firmware names first and
falls back to the generic `brcmfmac4359-sdio.bin`, which is present. WiFi
works.

## Known constraints

- `ufw` is enabled, but Docker's own iptables rules can bypass it for published
  ports. Documented in the board's `ROCKPRO64_SETUP.md`; consider `ufw-docker`
  if the board ever leaves a trusted segment.
- The board's clock and timezone are `Asia/Seoul` with NTP active — collector
  scheduling and `published_at` parsing depend on this.
- `/var/log` is on zram (50MB). Container logs live under `/var/lib/docker` on
  the microSD and are capped at `10m x 3` by both the daemon default and each
  service definition.
