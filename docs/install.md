# Installing Leidiniai on Home Assistant

The repository is private, so the Home Assistant app store can't add it as a repository. Instead the repo is
cloned into the `/addons` folder of Home Assistant OS, where the Supervisor picks it up as a **local app**.
Updating means `git pull` and then **Update** or **Rebuild** in the app's page.

Tested target: Home Assistant OS 18.4, Supervisor 2026.11.0, Core 2026.10.3, amd64 (ThinkPad X280).

Time needed: about 30 minutes, most of it the first image build (it downloads a headless Chromium, ~400 MB).
Disk: about 1.5 GB for the image, plus up to a few GB of leaflets (see `keep_pdf_weeks`).

## 1. Before you start

1. **Advanced mode**: click your user name (bottom left) → turn on **Advanced mode**. The Terminal & SSH app
   is only listed with it on.
2. **Mosquitto broker**: Settings → Apps → App store → **Mosquitto broker** → Install → Start.
   Then Settings → Devices & services: the **MQTT** integration is discovered – press **Configure** → Submit.
   (Skip if MQTT already works on this box.)
3. **Terminal & SSH**: Settings → Apps → App store → **Terminal & SSH** (the official one) → Install → Start →
   **Open Web UI**. All commands below run in that terminal. It has `git` and sees `/addons` and `/config`.

## 2. Deploy key (read-only access for this box)

A deploy key lets this one machine read this one repository; it can't push and can't see your other repos.
The key is kept in `/config/.ssh/` because the terminal app's home folder is not kept across restarts.

```sh
mkdir -p /config/.ssh && chmod 700 /config/.ssh
ssh-keygen -t ed25519 -N "" -C "ha-leidiniai" -f /config/.ssh/leidiniai_deploy
cat /config/.ssh/leidiniai_deploy.pub
```

Copy the line that starts with `ssh-ed25519`. On GitHub: **DG-Lt/lt-leidiniai → Settings → Deploy keys →
Add deploy key**, title `Home Assistant`, paste the key, leave **Allow write access** off → **Add key**.

Check that it works:

```sh
export GIT_SSH_COMMAND="ssh -i /config/.ssh/leidiniai_deploy -o IdentitiesOnly=yes -o UserKnownHostsFile=/config/.ssh/known_hosts -o StrictHostKeyChecking=accept-new"
ssh -T git@github.com
```

The first time it prints GitHub's key fingerprint. It must be
`SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU` (ED25519, as published on
https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints).
Then: `Hi DG-Lt/lt-leidiniai! You've successfully authenticated, but GitHub does not provide shell access.`

## 3. Clone into /addons

In the same terminal (the `export` above still applies):

```sh
git clone git@github.com:DG-Lt/lt-leidiniai.git /addons/lt-leidiniai
cd /addons/lt-leidiniai
git config core.sshCommand "$GIT_SSH_COMMAND"
ls leidiniai/config.yaml
```

`core.sshCommand` is stored in the clone, so later `git pull` works without the `export`.

## 4. Install the app

1. Settings → Apps → App store → ⋮ (top right) → **Check for updates**. Reload the page.
2. A **Local apps** section appears with **Leidiniai**. Open it → **Install**. This builds the image on the box
   (10–20 minutes, the page shows a spinner; the Supervisor log shows the progress).
3. **Configuration** tab – the defaults are fine to start with:

   | Option | Default | Meaning |
   |---|---|---|
   | `check_time` | `03:30` | nightly check; only chains whose leaflet ends within 2 days (or none yet) are checked |
   | `request_delay` | `2` | seconds between two requests to the same shop |
   | `threads` | `2` | PDF parsing / page rendering threads (keep 2–3) |
   | `chains` | all six | which chains to collect |
   | `browser_fallback` | on | headless Chromium when a page is blocked or needs JavaScript (Rimi always) |
   | `keep_pdf_weeks` | `8` | leaflet PDFs older than this are deleted (offers and prices stay) |
   | `keep_images_weeks` | `12` | product pictures older than this are deleted |
   | `log_level` | `info` | `debug` only while chasing a problem |

4. **Info** tab: turn on **Start on boot** and **Watchdog**, keep **Show in sidebar** on → **Start**.

## 5. Check that it works

1. **Log** tab: near the top `MQTT: connected`. No `ERROR` lines.
2. Sidebar → **Leidiniai** → **Būsena**: the version is the one in `leidiniai/config.yaml`, and
   *MQTT (Home Assistant)* shows **prisijungta**.
3. Settings → Devices & services → MQTT → **Devices**: a device **Leidiniai** with the entities listed in the
   app's Documentation tab (`sensor.leidiniai_iki_leaflet` … `button.leidiniai_check_now`).
4. Panel → **Leidiniai** → **Tikrinti visus dabar**. The first full check takes a while (IKI's PDF alone is
   ~50 MB; Rimi does ~200 e-shop lookups spaced out). Afterwards each chain shows its leaflet and offer count,
   **Pasiūlymai** lists offers, and `event.leidiniai_new_leaflet` has fired once per leaflet. Šilas shows
   **laukia skaitytuvo** (0 offers) until the vision parser is added.
5. **Būsena** → **Atsisiųsti žurnalus**: the ZIP opens and holds `leidiniai.log`, `runs/*.json` and `env.json`.
   This ZIP is what to send when something goes wrong.

If you don't need the first check right away, just wait: the nightly check at `check_time` does the same.

## 6. Updating

```sh
cd /addons/lt-leidiniai && git pull
```

Then Settings → Apps → **Leidiniai**:
- if the version in `leidiniai/config.yaml` changed: ⋮ → **Check for updates**, then **Update**;
- if only the code changed (same version): **Rebuild**.

The database, settings, logs and downloaded leaflets are kept (they live in the app's `/data`).
Read `leidiniai/CHANGELOG.md` for what changed.

Trying a pull request before it is merged:

```sh
cd /addons/lt-leidiniai
git fetch origin step5-mqtt && git checkout step5-mqtt    # the PR's branch
# … Rebuild, test …
git checkout main && git pull                              # back to main, Rebuild again
```

A version going **down** (e.g. back from a PR branch) is not offered as an update – use **Rebuild**.

## 7. Backups

The app is included in Home Assistant backups while running (`backup: hot`). Leaflet PDFs, the download cache and
temp files are left out of the backup (`pdf/`, `cache/`, `tmp/`); offers, prices, pictures, settings and logs
are in it. The deploy key in `/config/.ssh/` is in the backup too – it is read-only for this one repository; if a
backup is ever lost, delete the key on GitHub and make a new one.

## 8. Troubleshooting

| Symptom | Look at / do |
|---|---|
| No **Local apps** section | `ls /addons/lt-leidiniai/leidiniai/config.yaml`; ⋮ → **Check for updates**; Settings → System → Logs → **Supervisor** for a YAML error |
| Install / Rebuild fails | Supervisor log (the Docker build output); free disk space (Settings → System → Storage). The same build runs in GitHub CI on every PR – check whether it is green there |
| *MQTT* shows **išjungta** | App log: the line `MQTT off: …` says why. Mosquitto must be installed and running *before* Leidiniai starts – restart Leidiniai after installing it |
| *MQTT* shows **neprisijungta** | App log: `MQTT: connection refused …` or `disconnected`; check the Mosquitto broker app log |
| No device **Leidiniai** in MQTT | MQTT integration configured (step 1.2)? Restarting Home Assistant makes the app send discovery again |
| A chain shows an error | **Leidiniai** page → click the check for its summary; **Tikrinti dabar** on that chain's row tries again |
| `git pull` asks for a password or `Permission denied (publickey)` | `git -C /addons/lt-leidiniai config core.sshCommand` must show the `-i /config/.ssh/leidiniai_deploy` command; the deploy key still exists on GitHub |

If the MQTT line says the Supervisor service could not be read, the fallback is adding `hassio_api: true` to
`leidiniai/config.yaml` – report it first (with the logs ZIP) so it can be fixed in the repo.

## 9. Removing

1. Settings → Apps → Leidiniai → **Uninstall** (deletes its database, leaflets and logs).
2. `rm -rf /addons/lt-leidiniai`, then ⋮ → **Check for updates** in the app store.
3. GitHub → Settings → Deploy keys → delete `Home Assistant`; `rm /config/.ssh/leidiniai_deploy*`.
