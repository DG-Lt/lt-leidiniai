# Changelog

## 0.8.1
**Stebimi (watch list)**
- A watched word list now matches when **every word** is in the name, **in any order**: "Natura aliejus" finds
  "Saulėgrąžų aliejus NATURA*, 1,5 l" (0.8.0 found nothing). Same rule on the Stebimi page, in "Stebimi viršuje",
  `sensor.leidiniai_watched_on_sale` and `event.leidiniai_watch_hit`.
- **Tikslus žodis** per watched word (whole words only: "alus" no longer finds "natūralus"): tick it when adding,
  or on the word's heading.
- New view **Pagal tinklą**: shops with the most watched offers first, each offer once, the words that found them
  in the heading. The page remembers the chosen view.
- `event.leidiniai_watch_hit` fires only for leaflets that first appear after the word was added; reading a leaflet
  again (or a name fix) no longer makes its offers "new" (0.8.0 re-announced 11 offers after its re-parse).
- `sensor.leidiniai_watched_on_sale`: attributes `by_chain` (offers per shop, most first), `ending_soon`, and per
  item `terms` and `ending_soon`.

**Offers ending soon**
- New option **ending_soon_days** (default 3, 0 = off): the end date of an offer ending within that many days
  (today included) is highlighted on the cards and the details page.
- New filter **Besibaigiantys** in Pasiūlymai: only those offers.

**Other**
- Lidl: dates printed in front of a name ("11 21–11 22 PILOS / POLMLEK SVIESTAS …") become the offer's own dates and
  leave the name (also "Nuo šeštadienio, 11 21, iki 11 22" at the end).
- **Skaityti iš naujo** only marks the leaflet: it is read at night, or at once with "Skaityti paveikslėlius
  dabar" (the count on that button includes it).

## 0.8.0
**Picture reader (Šilas, Vynoteka drinks)**
- **Pictures are read at night only, on their own.** A check ("Tikrinti dabar" or the night check) only downloads
  a picture leaflet; the reading starts after the night's checks and never holds up a check of another shop.
  New button **Skaityti paveikslėlius dabar** (Leidiniai page and `button.leidiniai_read_pictures`) starts it at once.
- **Each page is saved as soon as it is read.** After a restart or an update the reading continues from the next
  page (at once if it is still night). **Skaityti iš naujo** on a picture leaflet reads it again from page 1; its
  offers stay on show meanwhile. To get the 0.8.0 pictures and dates for Šilas Nr. 23, press it once.
- **Better offer pictures:** the model's box is moved to the white card the offer is printed on (Šilas pages
  1–9: 94 cards). Pages without cards keep the model's box with a margin.
- **Offers' own dates** (Šilas "3D akcija – LAPKRIČIO 19–21 d.") instead of the leaflet's.
- **Memory:** the local model is unloaded after every page – no more prompt cache growth (0.7.0: ~200 MB a page).
- **Faster:** page pictures at the leaflet's own size (Šilas 1403 px instead of 1600 px: ~23 % fewer picture
  tokens, same detail; 1100 px lost too much text in a test), shorter answers (empty fields left out),
  3 CPU threads while reading pictures.
- The Ollama log no longer fills up with progress lines.

**Names and details**
- A name that is only a size ("cm", "24 cm", "2 vnt./rink. ml") shows **pavadinimas neatpažintas – žr. leidinio
  p. N** with a link to that page; a lone unit after a name is dropped ("Puodelių rinkinys ml").
- Lidl: promotion terms ("Akcijos limitas vieno pirkimo metu …", "Nuolaidos nesumuojamos", "Pasiūlymas galioja tik
  nurodytos akcijos metu …"), "Ieškoti šaldytuve", "Atsiprašome, šios prekės laikinai neturime" and product codes
  are left out of names.
- Long names are cut at the first full stop; the rest is the **Aprašymas** on the details page. Search and the
  watch list look at both.
- Details page: link to the **original leaflet at the offer's page** (while the file is kept) and to the leaflet
  on the shop's site; click the picture to enlarge it.
- PDF leaflets still valid are read again from the stored files at the next night check (new name rules).

**Home Assistant**
- `sensor.leidiniai_activity` ("laukia", "tikrinamas IKI", "Šilas: puslapis 3/12").
- `sensor.leidiniai_picture_reader` (paruoštas / ruošiamas / klaida / išjungtas, with the download progress).
- `event.leidiniai_watch_hit`: once per new watched offer (name, chain, price, discount, dates, link).
- Leaflet sensors: attribute `short_title` ("Maisto prekės", "Leidinys Nr. 23") for dashboard tables.
- Documentation: dashboard rows for the new entities and a watched-offer notification example.

## 0.7.0
- **New chain: Vynoteka** (https://vynoteka.lt/). **Already installed? Tick `vynoteka` under Chains in the
  Configuration tab** – an existing chain list is not changed by an update.
  - *Maisto leidinys* (PDF): offers with price, old price, discount ("-30" badges), "TIK" prices.
  - *Gėrimų leidinys*: pages of pictures only (~22) – read by the picture reader (`picture_reader`); with
    `none` it waits.
  - *Kalėdinių rinkinių katalogas*: every gift set with its price and contents, marked **katalogas**.
  - The winter catalogue is a video – skipped. Logo from the shop's site, own colour in the panel.
- Vynoteka gift sets count as alcohol unless the name says otherwise.

## 0.6.0
- **Picture reader for image-only leaflets** (Šilas, Rimi catalogues printed as pictures). New option
  `picture_reader`: `none` (as before, they wait), `tesseract` (light local OCR, ~25 MB) or `ollama` (vision
  model Qwen2.5-VL – on this box, or on another computer with `ollama_url`; `ollama_model` picks the model).
  Choosing one downloads what it needs in the background; switching away deletes it. Its state is on **Būsena**.
  Leaflets that waited ("laukia skaitytuvo") are read at the next night check once the reader is ready. See the
  Documentation tab for sizes and setup.
- The logs ZIP also holds the picture reader state and the Ollama server log.

## 0.5.2
- **Rimi alcohol catalogue Nr. 23 is read now.** 0.4.6 had filed it as "laukia skaitytuvo" (pictures only), so the
  viewer's PDF button of 0.5.1 never ran for it. Such Rimi leaflets are downloaded once more at the next Rimi
  check (which now also happens whenever a leaflet waits to be downloaded). The parser learnt while downloading
  (catalogue) is no longer forgotten when the listing is read again.
- IKI names: the vertical **SUPERKAINA** badge read letter by letter ("… 1 l A K I E P R U S") and the
  promotion sentence ("Pasiūlymas galioja iki … Nuolaida suteikiama tik pažymėtoms prekėms.") are left out.
  The IKI leaflets still valid are read again from the stored PDFs at the next IKI check.

## 0.5.1
- **Rimi alcohol assortment catalogue**: catalogues without product links now get their PDF from the viewer's
  "Atsiųsti PDF rinkmeną" button (headless browser). If it prints prices, every item is listed with its regular
  price, volume, price per litre and picture, marked **katalogas** (no discount – these are not promotions;
  hidden when "tik su nuolaida" is ticked). Nr. 23 gives 70 items, valid 2026-11-17 – 11-30. The one that waited
  is picked up at the next Rimi check.
- Logos: a newly uploaded logo shows at once (the browser kept the old picture for up to an hour).
- Categories: brand names printed in capitals no longer decide the category ("Alus GENYS BALTAS MELAS" is beer,
  not blueberries; "CONO SUR" wine is not a ready meal); "spiritinis gėrimas" is alcohol.

## 0.5.0
- **Categories learn from the shops and from you.** Maxima and Rimi sort every offer into their own categories,
  and your corrections count three times as much: a product now gets the category of the most similar of those
  products (sharing at least two significant words). The product page says "pagal panašius produktus" then.
  Every correction re-sorts the other products straight away; after each check all products not set by hand
  are sorted again, so it improves as more leaflets come in. On the first start all of them are re-sorted once.
- Words in genitive plural ("česnakų", "žolelių") describe a product and no longer decide its category:
  "Krevetės žolelių ir česnakų marinate" → Žuvis. "Kremas" alone is no longer cosmetics (only "veido / rankų /
  kūno … kremas" are), "skalbimo kapsulės" are household, not coffee.
- **Norfa: promotions from the website** (https://www.norfa.lt/akciju-puslapiai/akcijos/) – the short offers that
  are not in the leaflet (fish counter, weekend discounts …): price or percentage, dates, picture; news and
  games on that page are skipped. Read at every Norfa check (a few pages, spaced as usual).
- Leaflets that print no prices at all (the IKI and Rimi wine award catalogues) are no longer reported as a
  problem.

## 0.4.7
- Logos: no white box around them any more; empty margins around a logo are cut off automatically (also for the
  logos already saved). When uploading, **be balto fono** (on by default) makes the white background around your
  logo transparent – white letters inside the logo stay. The product page shows the logo too.
- **Tikslus žodis** checkbox on Pasiūlymai: search words must match whole words (any order) – "alus" no longer
  finds "Natūralus". Note: Lithuanian endings count, so "alus" won't find "alaus".
- IKI Nr. 47 offers had no validity dates (stored before 0.4.1 knew them): offers now take their leaflet's dates,
  for the existing ones too (database update 4).

## 0.4.6
- Rimi: catalogues without product links (the alcohol catalogue Nr. 23, the wine championship catalogue) no
  longer end the check with an error and are not retried every night: they are kept as **laukia skaitytuvo**
  (pictures only, for the later picture-reader step, like Šilas). The one that failed is fixed at the next Rimi check.

## 0.4.5
- Offer cards show the chain's logo. It is downloaded once from the shop's own site after that chain's next check
  (refreshed every 30 days); on **Būsena → Tinklų logotipai** you can upload your own file instead (PNG, JPG, WEBP,
  SVG, up to 512 KB). Without a logo the coloured name is shown as before.
- **Pasiūlymai**: new checkbox **Stebimi viršuje** – offers matching the watch list come first, the rest follow; both
  groups keep the chosen sort, and all other filters still apply.

## 0.4.4
- Rimi: the e-shop look-ups (one per product spot, `request_delay` apart – about 15–20 min for the weekly leaflet at
  4 s) now log the expected time at the start and progress every 25 look-ups, so a long check no longer looks stuck.
- Rimi: a product already looked up for another leaflet in the same check is not asked again.

## 0.4.3
- Maxima: 0.4.2 still found no offers – the page writes the id attribute as `data-offerCard-offer-id` (capital C)
  and the check was case-sensitive. Fixed; the test page now uses the same spelling.

## 0.4.2
- Maxima: offers were not found since Maxima changed its offer ids (numbers → UUIDs on 2026-11-20); fixed.
  New Maxima sections mapped: Buitinė chemija → Namų priežiūra, Prekės gyvūnams → Gyvūnams, Konditerija → Duona ir
  kepiniai. "Only in some shops" notes are kept with the offer.
- Panel serves 8 requests at a time (pictures load faster, no "Task queue depth" warnings).

## 0.4.1
- IKI: only leaflets are collected – the policy PDFs linked in the iki.lt footer were taken for leaflets and are
  removed from the database on update. The leaflet title and dates now come from the page
  ("IKI Kainų leidinys Nr. 47", 2026-11-16 – 11-22) instead of the button text; the leaflet already stored gets
  them at its next check.
- IKI: the other leaflets under "Kiti IKI leidiniai" (store offers, catalogues) are collected too.
- Dates written as "2026 11 16" are understood.

## 0.4.0
- Home Assistant entities over MQTT discovery (needs the Mosquitto broker app; credentials come from the
  Supervisor): a leaflet sensor per chain, **Naujas leidinys** event, **Stebimi akcijose** (watched offers valid
  today), **Problema**, **Tikrinti dabar** button, last and next check times. See the Documentation tab.
- Būsena shows whether MQTT is connected.

## 0.3.0
- Log files: `/data/logs/leidiniai.log`, 5 MB × 10 rotating; checks run in a child process keep their
  warning/error level in the file.
- Every check writes a summary (chain, leaflets, counts, warnings, errors, timings) to `/data/logs/runs/`
  (newest 200 kept); click a check on the **Leidiniai** page to see it.
- **Atsisiųsti žurnalus** (Būsena and Leidiniai pages): ZIP with the log files, the last 20 check summaries
  and `env.json` (version, options, database counts, disk use) – nothing secret, for debugging.
- **Būsena** shows the last log lines.

## 0.2.0
- Leaflet checks for all six chains, gentle downloads with a headless-browser fallback, nightly scheduler.
- Offers are read from the leaflets: IKI, Lidl, Norfa PDFs (text layer), Maxima offers page, Rimi hotspots
  with e-shop lookups. Šilas waits for the vision parser.
- Prices in cents, product history, categories (shop categories + Lithuanian keyword dictionary; your
  corrections are remembered), product pictures cut from the leaflet pages.
- Panel: **Pasiūlymai** (search, chain, category, sort, only discounted, without card), product page with
  the price history and category correction, **Stebimi** (watch list).
- Leaflet files are deleted after `keep_pdf_weeks`, pictures after `keep_images_weeks`.

## 0.1.0
- App skeleton: ingress panel (Lithuanian), options, data folder.
