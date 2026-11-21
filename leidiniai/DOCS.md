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
  An offer whose name could not be read shows **pavadinimas neatpažintas – žr. leidinio p. N** with a link to that
  page of the leaflet. Long names are cut at the first full stop: the rest is the **Aprašymas** on the details page;
  search and the watch list look at both.
  The details page links to the **original leaflet at the offer's page** (while the file is kept, `keep_pdf_weeks`)
  and to the leaflet on the shop's site; click the picture to enlarge it.
- **Stebimi** – the watch list: words to look for in every new leaflet, with the matching offers.
- **Leidiniai** – leaflets found, their state, the last checks (click one for its summary), what runs now, a
  "check now" button, **Skaityti paveikslėlius dabar** and, on a picture leaflet, **Skaityti iš naujo** (see
  Picture reader).
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
| `sensor.leidiniai_<chain>_leaflet` (iki, lidl, maxima, norfa, rimi, silas, vynoteka) | title of the leaflet valid today; attributes `short_title` (fits a table: "Maisto prekės", "Leidinys Nr. 23"), `valid_from`, `valid_to`, `offers`, `url`, `current`, `upcoming` (each with `short_title` too), `last_check`, `last_error` |
| `event.leidiniai_new_leaflet` | fires `new_leaflet` once per leaflet that is ready to look at, with `chain`, `chain_name`, `title`, `valid_from`, `valid_to`, `offers`, `url` |
| `sensor.leidiniai_watched_on_sale` | how many watched (Stebimi) offers are valid today; attribute `items` (name, chain, price €, old price, discount, card, valid to – up to 40) |
| `binary_sensor.leidiniai_problem` | on when a check or a leaflet failed; attribute `problems` |
| `button.leidiniai_check_now` | queues a check of all chains |
| `sensor.leidiniai_last_run`, `sensor.leidiniai_next_check` | time of the last finished / next check |
| `sensor.leidiniai_activity` | what runs now: `laukia`, `tikrinamas IKI`, `Šilas: puslapis 3/12`, `paveikslėliai laukia eilėje` (several joined with "; "); attributes `checking`, `queued_checks`, `pictures` (chain, title, page, pages) |
| `sensor.leidiniai_picture_reader` | `paruoštas`, `ruošiamas`, `klaida` or `išjungtas`; attribute `message` (e.g. "atsisiunčiamas modelis qwen2.5vl:7b 40%"), `model`, `updated` |
| `event.leidiniai_watch_hit` | fires `watch_hit` once per new watched offer (from a leaflet read after the word was added to Stebimi): `term`, `chain_name`, `name`, `price`, `old_price`, `discount`, `card`, `valid_from`, `valid_to`, `leaflet`, `url` (the offer's page in this panel) |
| `button.leidiniai_read_pictures` | reads the picture leaflets that wait now instead of at night |

Example – a phone notification for each watched offer (the event entity's own trigger, HA 2026.7+):

```yaml
triggers:
  - trigger: event.received
    target:
      entity_id: event.leidiniai_watch_hit
    options:
      event_type:
        - watch_hit
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: "{{ trigger.to_state.attributes.chain_name }}: {{ trigger.to_state.attributes.name }}"
      message: >-
        {{ trigger.to_state.attributes.price }} € {{ trigger.to_state.attributes.discount or '' }},
        iki {{ trigger.to_state.attributes.valid_to }}
      data:
        clickAction: "{{ trigger.to_state.attributes.url }}"
```

`event.leidiniai_new_leaflet` works the same way with event type `new_leaflet`.

### Dashboard rows (expander-card + multiple-entity-row)
For a "Tikrinimas" expander: what runs now, the picture reader's state, and an icon that starts the picture reading
after a confirmation (no exposed Press button):

```yaml
type: entities
entities:
  - type: custom:multiple-entity-row
    entity: sensor.leidiniai_activity
    name: Dabar
    secondary_info:
      entity: sensor.leidiniai_picture_reader
      name: "Skaitytuvas:"
    entities:
      - entity: button.leidiniai_read_pictures
        name: false
        icon: mdi:image-search-outline
        tap_action:
          action: perform-action
          perform_action: button.press
          target:
            entity_id: button.leidiniai_read_pictures
          confirmation:
            text: Skaityti paveikslėlius dabar? Tai užtrunka valandas (~10 min. puslapiui).
```

In a leaflets table use the attribute `short_title` instead of the state (the full Lidl and Maxima titles are long).

## Picture reader (image-only leaflets)
Šilas, the Vynoteka drinks leaflet and some Rimi catalogues are published as pictures only, with no text inside. They show
**laukia skaitytuvo** until a picture reader is chosen in the Configuration tab (`picture_reader`):

| Option | What it needs | Quality |
|---|---|---|
| `none` (default) | nothing | image-only leaflets wait |
| `tesseract` | ~25 MB language files (downloaded into the app's data) | reads names and plainly printed prices; often misses big stylised prices. Fine for a small HA box |
| `ollama` | **on this box**: the Ollama runtime (~1.5 GB download, ~100 MB kept) and the model (`qwen2.5vl:7b` ~6 GB; ~8–10 GB RAM while reading). **With `ollama_url`**: nothing here – an Ollama on another computer does the work | best: names with Lithuanian letters, prices, old prices, discounts, card prices, picture of each offer |

Choosing a reader downloads what it needs in the background (progress on **Būsena** → "Paveikslėlių skaitytuvas",
in the log and in `sensor.leidiniai_picture_reader`); switching to another reader deletes the files of the old one.
These files are not in backups.

**When pictures are read.** A check ("Tikrinti dabar", the night check) only downloads a picture leaflet. Reading it
takes hours on a laptop CPU, so it runs on its own after the night's checks have finished (they may download new
picture leaflets), and never holds up a check. **Skaityti paveikslėlius dabar** (Leidiniai page, or
`button.leidiniai_read_pictures`) starts it at once. With a local Ollama on an i5-8350U (3 threads, lowest priority)
expect roughly 10–15 minutes per page: Šilas (12 pages) about 2–3 hours, the Vynoteka drinks leaflet (22 pages)
about 4–5 hours.

**Each page is saved as soon as it is read.** After a restart or an update the reading continues from the next
page – at once if it is still night, otherwise at the next night or with the button. **Skaityti iš naujo** reads a
leaflet again from the first page (e.g. after an update of the reader); its offers stay on show until then.

**Memory.** The local model (~6 GB) is unloaded after every page, which also clears llama-server's prompt cache
(0.7.0 grew ~200 MB per page). Loading it again takes seconds.

**Pictures of offers.** Most picture leaflets print each offer on a white card; the box the model gives is moved
to the card it falls in, so the picture shows the whole card. Pages without cards (a free collage) keep the model's
own box with a small margin. Offers with their own dates printed on them (Šilas "3D akcija – LAPKRIČIO 19–21 d.")
get those dates instead of the leaflet's.

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
