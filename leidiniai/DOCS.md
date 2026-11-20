# Leidiniai

Collects the discount leaflets of IKI, Rimi, Maxima, Norfa, Lidl, Šilas and Vynoteka, extracts the offers and keeps their price history. Everything runs locally on this machine; no cloud AI.

Open the **Leidiniai** panel in the sidebar. Options are explained in the Configuration tab.

## Panel
- **Pasiūlymai** – the offers valid now (or starting soon): search without Lithuanian letters
  ("sviest" finds "Sviestas"), filter by chain and category, sort by discount, price or unit price.
  Click an offer for its price history, the same product in other chains and the category correction.
  "Įsiminti raktažodį" (remember keyword) teaches the category dictionary; all products not set by hand are
  then sorted again.
  **Stebimi viršuje** puts the watch-list matches first (other filters and the sort still apply).
  **Tikslus žodis** matches whole words only (any order). **Netrukus** lists offers that start later – usually the
  next week's leaflets, which appear a few days before they start.
- **Stebimi** – the watch list: words to look for in every new leaflet, with the matching offers.
- **Leidiniai** – leaflets found, their state, the last checks (click one for its summary) and a "check now" button.
- **Būsena** – version, options, **Tinklų logotipai** (chain logos: downloaded from the shops' sites, or upload your
  own), the last log lines and **Atsisiųsti žurnalus**.

## Categories
A product's category comes from, in this order: the shop's own category (Maxima, Rimi) → a keyword you taught
("Įsiminti raktažodį") → the category of the most similar products that a shop or you have categorised →
the built-in keyword list. Every correction you make counts for similar products too and re-sorts them at once;
products you set by hand never change by themselves.

Norfa's website promotions (fish counter, weekend discounts …) are listed next to the Norfa leaflet.

**Vynoteka**: the food leaflet (PDF) is read like the others; the drinks leaflet is pages of pictures (needs the
picture reader, ~22 pages); the gift set catalogue lists each set with its price and contents, marked
**katalogas**. The winter catalogue is a video and is skipped.

## Home Assistant entities
Install the **Mosquitto broker** app and the MQTT integration first; Leidiniai finds the broker by itself.
All entities belong to the device **Leidiniai**:

| Entity | Shows |
|---|---|
| `sensor.leidiniai_<chain>_leaflet` (iki, lidl, maxima, norfa, rimi, silas, vynoteka) | title of the leaflet valid today; attributes `valid_from`, `valid_to`, `offers`, `url`, `current`, `upcoming`, `last_check`, `last_error` |
| `event.leidiniai_new_leaflet` | fires `new_leaflet` once per leaflet that is ready to look at, with `chain`, `chain_name`, `title`, `valid_from`, `valid_to`, `offers`, `url` |
| `sensor.leidiniai_watched_on_sale` | how many watched (Stebimi) offers are valid today; attribute `items` (name, chain, price €, old price, discount, card, valid to – up to 40) |
| `binary_sensor.leidiniai_problem` | on when a check or a leaflet failed; attribute `problems` |
| `button.leidiniai_check_now` | queues a check of all chains |
| `sensor.leidiniai_last_run`, `sensor.leidiniai_next_check` | time of the last finished / next check |

Example – a phone notification for each new leaflet:

```yaml
triggers:
  - trigger: state
    entity_id: event.leidiniai_new_leaflet
    not_from: unavailable
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: "Naujas {{ trigger.to_state.attributes.chain_name }} leidinys"
      message: >-
        {{ trigger.to_state.attributes.title }} ({{ trigger.to_state.attributes.valid_from }} –
        {{ trigger.to_state.attributes.valid_to }}), pasiūlymų: {{ trigger.to_state.attributes.offers }}
```

## Picture reader (image-only leaflets)
Šilas, the Vynoteka drinks leaflet and some Rimi catalogues are published as pictures only, with no text inside. They show
**laukia skaitytuvo** until a picture reader is chosen in the Configuration tab (`picture_reader`):

| Option | What it needs | Quality |
|---|---|---|
| `none` (default) | nothing | image-only leaflets wait |
| `tesseract` | ~25 MB language files (downloaded into the app's data) | reads names and plainly printed prices; often misses big stylised prices. Fine for a small HA box |
| `ollama` | **on this box**: the Ollama runtime (~1.5 GB download, ~100 MB kept) and the model (`qwen2.5vl:7b` ~6 GB; ~8–10 GB RAM while reading). **With `ollama_url`**: nothing here – an Ollama on another computer does the work | best: names with Lithuanian letters, prices, old prices, discounts, card prices, picture of each offer |

Choosing a reader downloads what it needs in the background (progress on **Būsena** → "Paveikslėlių skaitytuvas" and
in the log); switching to another reader deletes the files of the old one. These files are not in backups.
With a local Ollama, it runs only while an image-only leaflet is read (at the night check, lowest priority, the
`threads` option sets its CPU threads) and frees its memory two minutes after the last page; expect about 1–3
minutes per page on a laptop CPU. Leaflets that waited are read at the next night check once the reader is ready.

For an external Ollama: install Ollama on the PC, run `ollama pull qwen2.5vl:7b` there, make it listen on the
network (`OLLAMA_HOST=0.0.0.0`) and set `ollama_url`, e.g. `http://192.168.1.20:11434`. The model is never pulled
onto another computer from here. Offers read from pictures are marked in the offer details (`vision` / `ocr`).

## Logs
Logs are in the app's **Log** tab and in `/data/logs/leidiniai.log` (5 MB × 10 files). When something looks
wrong, press **Atsisiųsti žurnalus** on the Būsena page: the ZIP holds the log files, the last 20 check
summaries and `env.json` (version, options, database counts, disk use). It contains no passwords.

Offers are read from the leaflet as printed. Some cells of a leaflet are hard to read automatically:
an offer without a name shows its picture so you can still see it. Rimi prices come from the Rimi e-shop
and can differ from the paper leaflet.

Install and update steps: see `docs/install.md` in the repository.
