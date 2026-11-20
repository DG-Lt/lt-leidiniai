# Changelog

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
