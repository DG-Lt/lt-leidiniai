# Installing Leidiniai on Home Assistant

The repository is public, so it is added to the Home Assistant app store like any other app repository:
no SSH key, no terminal, and new versions show up as **Update** by themselves.

Tested target: Home Assistant OS 18.4, Supervisor 2026.11.0, Core 2026.10.3, amd64 (ThinkPad X280).
Time: about 30 minutes, most of it the first build (the box builds the app itself and downloads a headless
Chromium, ~400 MB). Disk: about 1.5 GB for the app, plus the leaflets it keeps (see `keep_pdf_weeks`).

**MQTT.** Leidiniai needs the Mosquitto broker app and the MQTT integration. If MQTT already works (e.g. for
Zigbee2MQTT), there is nothing to do: Leidiniai asks the Supervisor for login details and the Mosquitto app gives
it its own automatic user, so your Mosquitto and Z2M settings don't change. Leidiniai only uses the topics
`homeassistant/<type>/leidiniai/…` (discovery) and `leidiniai/…`.

## 1. Add the repository

1. Settings → Apps → **App store** (button bottom right).
2. ⋮ (top right) → **Repositories**.
3. Paste `https://github.com/DG-Lt/lt-leidiniai` → **Add** → **Close**.
4. Reload the page (F5). Scroll down: a section **lt-leidiniai** with the app **Leidiniai** appears.

## 2. Install

1. Click **Leidiniai** → **Install**. The box builds the app: 10–20 minutes with only a spinner. To watch it:
   Settings → System → Logs → choose **Supervisor** (top right).
2. **Configuration** tab – the defaults are fine to start with:

   | Option | Default | Meaning |
   |---|---|---|
   | `check_time` | `03:30` | nightly check; only chains whose leaflet ends within 2 days (or none yet) are checked |
   | `request_delay` | `2` | seconds between two requests to the same shop |
   | `threads` | `2` | PDF parsing / page rendering threads (keep 2–3, HA shares the CPU) |
   | `chains` | all six | which chains to collect |
   | `browser_fallback` | on | headless Chromium when a page is blocked or needs JavaScript (Rimi always) |
   | `keep_pdf_weeks` | `8` | leaflet PDFs older than this are deleted (offers and prices stay) |
   | `keep_images_weeks` | `12` | product pictures older than this are deleted |
   | `log_level` | `info` | `debug` only while chasing a problem |

   Press **Save** if you changed something.
3. **Info** tab: turn on **Start on boot** and **Watchdog**, keep **Show in sidebar** on → **Start**.

## 3. Check that it works

1. **Log** tab (press *Refresh*): `MQTT: connected` near the top, no `ERROR` lines.
2. Sidebar → **Leidiniai** → **Būsena**: the version shown on the app page, and *MQTT (Home Assistant)*
   **prisijungta**.
3. Settings → Devices & services → **MQTT** → devices: **Leidiniai**, with entities like
   `sensor.leidiniai_iki_leaflet` and `button.leidiniai_check_now` (full list in the app's Documentation tab).
4. Panel → **Leidiniai** page → **Tikrinti visus dabar**. The first check of all chains takes a while (IKI's PDF
   is ~50 MB; Rimi does ~200 e-shop look-ups spaced out). Then each chain shows its leaflet and offer count, and
   **Pasiūlymai** lists offers. Šilas shows **laukia skaitytuvo** (0 offers) until its picture reader is added.
   You can also just wait – the nightly check does the same.
5. **Būsena** → **Atsisiųsti žurnalus**: a ZIP with `leidiniai.log`, `runs/…json` and `env.json`. That ZIP is
   what to give Claude when something goes wrong.

## 4. Updates

Every change to the app merged into `main` raises the version in `leidiniai/config.yaml`. The Supervisor looks at the
repository on its own from time to time; to look right away: App store → ⋮ → **Check for updates**. The app then
shows **Update** (and Settings shows it with the other updates). What changed: the app's **Changelog**.

The database, settings, logs and leaflets are kept across updates – they live in the app's own data folder.

A pull request is not on the box until it is merged; its CI already builds and smoke-tests the app image.

## 5. Backups

The app is in Home Assistant backups (`backup: hot`, it keeps running). Leaflet PDFs, the download cache and temp
files are left out (`pdf/`, `cache/`, `tmp/`); offers, prices, pictures, settings and logs are in.

## 6. Troubleshooting

| Symptom | Look at / do |
|---|---|
| Repository added but no **Leidiniai** | Reload the page; App store → ⋮ → **Check for updates**; Settings → System → Logs → **Supervisor** for the error |
| Install / Update fails | Supervisor log (the build output); free disk (Settings → System → Storage). GitHub runs the same build on every PR – check it is green there |
| *MQTT* shows **išjungta** | App log: the line `MQTT off: …` says why. Restart Leidiniai once Mosquitto is running |
| *MQTT* shows **neprisijungta** | App log: `MQTT: connection refused …` or `disconnected`; Mosquitto broker app log |
| No device **Leidiniai** under MQTT | Restart Leidiniai; restarting Home Assistant also makes it send the devices again |
| A chain shows an error | **Leidiniai** page → click that check for its summary; **Tikrinti dabar** on that row tries again |

If the log says the Supervisor's MQTT service could not be read, the fix is adding `hassio_api: true` to
`leidiniai/config.yaml` – send the logs ZIP to Claude first so it is fixed in the repository.

## 7. Removing

1. Settings → Apps → Leidiniai → **Uninstall** (deletes its database, leaflets and logs).
2. App store → ⋮ → **Repositories** → remove `https://github.com/DG-Lt/lt-leidiniai`.
