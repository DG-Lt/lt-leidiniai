# Installing Leidiniai on Home Assistant

Tested target: Home Assistant OS 18.4, Supervisor 2026.11.0, Core 2026.10.3, amd64 (ThinkPad X280).
Time: about 30 minutes, most of it the first build (it downloads a headless Chromium, ~400 MB).
Disk: about 1.5 GB for the app image, plus the leaflets it keeps (a few hundred MB per week, see `keep_pdf_weeks`).

## 0. What happens and why

**How a local app gets onto Home Assistant.** Home Assistant OS has a folder `/addons`. Every sub-folder in it
that has a `config.yaml` shows up in the app store under **Local apps**, and the Supervisor builds it right on
the box from its `Dockerfile`. So installing = putting this repository into `/addons/lt-leidiniai`, then pressing
**Install**. Updating = refreshing that folder (`git pull`) and pressing **Update** / **Rebuild**.

**Why a deploy key.** The repository `DG-Lt/lt-leidiniai` is private, so GitHub only hands it out to someone who
proves they are allowed. Home Assistant can't type your GitHub password, so it gets its own key:

- you make an SSH key pair on the Home Assistant box (two files: the *private* key stays on the box, the
  *public* key is one line of text you paste into GitHub);
- on GitHub you add the public key as a **deploy key** of this one repository, without write access.

That key can only **read this one repository** – it can't push, can't see your other repositories and isn't
your account password. If the box is ever lost, you delete the key on GitHub and nothing else is affected.
(The alternative, a personal access token, is tied to your whole account – a deploy key is the narrower choice.)

> **Simpler alternative:** if you make the repository **public** (GitHub → Settings → General → Danger Zone →
> Change visibility), none of the key and terminal steps are needed: add `https://github.com/DG-Lt/lt-leidiniai`
> under Settings → Apps → App store → ⋮ → **Repositories**, and updates then appear by themselves like for any
> other app. The code holds no passwords. Tell Claude if you go this way – the guide gets a short version.

**Why Terminal & SSH, and for how long.** `git` (to fetch the repository) runs in a terminal on the box, and the
Terminal & SSH app is that terminal. It is needed **only while installing and when you update** (`git pull`).
Leidiniai does not use it – stop it afterwards (Info tab → **Stop**, and turn off *Start on boot*).

**About VS Code (Studio Code Server).** It shows the `/config` folder. You don't need it for this guide.
`/config/.ssh/` won't be there until step 2 creates it, and folders starting with a dot may be hidden in the file
tree – that is fine, you never need to open it. `/addons` is a different folder and is not in that tree either.

**Your Mosquitto and Zigbee2MQTT keep working.** Leidiniai asks the Supervisor for MQTT login details; the
Mosquitto app gives every app that asks its own automatic user, so nothing in your Mosquitto or Z2M setup
changes. Leidiniai only uses the topics `homeassistant/<type>/leidiniai/…` (discovery) and `leidiniai/…`.
Since MQTT already works on your box, there is nothing to set up for it.

## 1. Open the terminal

1. Settings → Apps → **Terminal & SSH** → **Start** (if it is stopped) → **Open Web UI**.
   A black terminal window opens with a prompt like `[core-ssh ~]$`.
2. Pasting: **right-click → Paste**, or **Ctrl+Shift+V**. Paste one grey block at a time and press **Enter**.

Quick check that the folders are there:

```sh
ls -d /addons /config && git --version
```

Expected: `/addons  /config` and `git version 2.…`.

## 2. Make the deploy key

```sh
mkdir -p /config/.ssh && chmod 700 /config/.ssh
ssh-keygen -t ed25519 -N "" -C "ha-leidiniai" -f /config/.ssh/leidiniai_deploy
```

This makes two files: `/config/.ssh/leidiniai_deploy` (private – never share it) and
`/config/.ssh/leidiniai_deploy.pub` (public). They are in `/config` because the terminal app forgets its own
home folder when it restarts; `/config` is kept (and is in your backups).

Show the public key:

```sh
cat /config/.ssh/leidiniai_deploy.pub
```

It prints one line: `ssh-ed25519 AAAA…… ha-leidiniai`. Select the whole line with the mouse and copy it
(right-click → Copy).

## 3. Add the key on GitHub

1. Open https://github.com/DG-Lt/lt-leidiniai/settings/keys (repository → **Settings** → **Deploy keys**).
2. **Add deploy key**.
3. Title: `Home Assistant`. Key: paste the line. **Allow write access: leave unticked.**
4. **Add key** (GitHub may ask for your password or 2FA).

## 4. Test the key

Back in the terminal:

```sh
export GIT_SSH_COMMAND="ssh -i /config/.ssh/leidiniai_deploy -o IdentitiesOnly=yes -o UserKnownHostsFile=/config/.ssh/known_hosts -o StrictHostKeyChecking=accept-new"
$GIT_SSH_COMMAND -T git@github.com
```

The `export …` line tells git which key to use (only for this terminal window); the second line connects to
GitHub with that key. Expected output:

```
Warning: Permanently added 'github.com' (ED25519) to the list of known hosts.
Hi DG-Lt/lt-leidiniai! You've successfully authenticated, but GitHub does not provide shell access.
```

`Permission denied (publickey)` means the key wasn't added (step 3) or was copied incompletely.

Optional, to be sure you talk to the real GitHub: `ssh-keygen -lf /config/.ssh/known_hosts` must show
`SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU` (GitHub publishes it at
https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints).

## 5. Fetch the repository into /addons

In the same terminal window (the `export` from step 4 must still be active – if you closed the window,
paste that `export` line again first):

```sh
git clone git@github.com:DG-Lt/lt-leidiniai.git /addons/lt-leidiniai
cd /addons/lt-leidiniai
git config core.sshCommand "$GIT_SSH_COMMAND"
git log --oneline -1 && grep ^version leidiniai/config.yaml
```

The `git config` line saves the key choice inside the clone, so later updates are just `git pull`.
Expected: the newest commit and `version: "0.4.0"` (or newer).

## 6. Install the app

1. Settings → Apps → **App store** (button bottom right) → ⋮ (top right) → **Check for updates**.
   Reload the page (F5).
2. Scroll down: a section **Local apps** with **Leidiniai** appears. Click it → **Install**.
   The box now builds the app: 10–20 minutes, only a spinner is shown. To watch progress: Settings → System →
   Logs → choose **Supervisor** top right.
3. When done, the app page has the tabs Info / Documentation / Configuration / Log.
4. **Configuration** tab – the defaults are fine to start with; change only if you want:

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
5. **Info** tab: turn on **Start on boot** and **Watchdog**, keep **Show in sidebar** on → **Start**.

## 7. Check that it works

1. **Log** tab (press *Refresh*): you should see `MQTT: connected` near the top and no `ERROR` lines.
2. Sidebar → **Leidiniai** → **Būsena**: the version matches `leidiniai/config.yaml`, and *MQTT (Home
   Assistant)* shows **prisijungta**.
3. Settings → Devices & services → **MQTT** → devices: **Leidiniai** is there, with entities like
   `sensor.leidiniai_iki_leaflet` and `button.leidiniai_check_now` (full list in the app's Documentation tab).
4. Panel → **Leidiniai** page → **Tikrinti visus dabar**. The first check of all chains takes a while (IKI's PDF
   is ~50 MB; Rimi does ~200 e-shop look-ups spaced out). Then each chain shows its leaflet and offer count, and
   **Pasiūlymai** lists offers. Šilas shows **laukia skaitytuvo** (0 offers) until its picture reader is added.
   You can also skip this – the nightly check does the same.
5. **Būsena** → **Atsisiųsti žurnalus**: a ZIP downloads with `leidiniai.log`, `runs/…json` and `env.json`.
   That ZIP is what to give Claude when something goes wrong.

Finally stop Terminal & SSH if you don't use it otherwise.

## 8. Updating later

1. Start **Terminal & SSH** → Open Web UI, then:

   ```sh
   cd /addons/lt-leidiniai && git pull
   ```

2. Settings → Apps → **Leidiniai**:
   - if the version changed (see `leidiniai/CHANGELOG.md`): App store → ⋮ → **Check for updates**, then the app
     shows **Update** – press it;
   - if the version is the same (only code fixes): ⋮ → **Rebuild**.
3. Stop Terminal & SSH again.

The database, settings, logs and leaflets are kept – they live in the app's own data folder, not in `/addons`.

Trying a pull request before merging it:

```sh
cd /addons/lt-leidiniai
git fetch origin <branch> && git checkout <branch>    # the PR's branch name
# … Rebuild, test …
git checkout main && git pull                          # back to main, Rebuild again
```

Going back to a lower version is not offered as an update – use **Rebuild**.

## 9. Backups

The app is in Home Assistant backups (`backup: hot`, it keeps running). Leaflet PDFs, the download cache and temp
files are left out (`pdf/`, `cache/`, `tmp/`); offers, prices, pictures, settings and logs are in. The deploy key
in `/config/.ssh/` is in the backup too – it can only read this repository; if a backup ever gets lost, delete
the key on GitHub and make a new one.

## 10. Troubleshooting

| Symptom | Look at / do |
|---|---|
| No **Local apps** section | `ls /addons/lt-leidiniai/leidiniai/config.yaml` must exist; App store → ⋮ → **Check for updates**, reload; Settings → System → Logs → **Supervisor** for a YAML error |
| Install / Rebuild fails | Supervisor log (the build output); free disk (Settings → System → Storage). GitHub runs the same build on every PR – check it is green there |
| *MQTT* shows **išjungta** | App log: the line `MQTT off: …` says why. Restart Leidiniai once Mosquitto is running |
| *MQTT* shows **neprisijungta** | App log: `MQTT: connection refused …` or `disconnected`; Mosquitto broker app log |
| No device **Leidiniai** under MQTT | Restart Leidiniai; restarting Home Assistant also makes it send the devices again |
| A chain shows an error | **Leidiniai** page → click that check for its summary; **Tikrinti dabar** on that row tries again |
| `git pull`: `Permission denied (publickey)` | `git -C /addons/lt-leidiniai config core.sshCommand` must print the `-i /config/.ssh/leidiniai_deploy …` line; the deploy key must still be on GitHub |

If the log says the Supervisor's MQTT service could not be read, the fix is adding `hassio_api: true` to
`leidiniai/config.yaml` – send the logs ZIP to Claude first so it is fixed in the repository.

## 11. Removing

1. Settings → Apps → Leidiniai → **Uninstall** (deletes its database, leaflets and logs).
2. In the terminal: `rm -rf /addons/lt-leidiniai`, then App store → ⋮ → **Check for updates**.
3. GitHub → repository Settings → Deploy keys → delete `Home Assistant`; `rm /config/.ssh/leidiniai_deploy*`.
