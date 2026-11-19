# Changelog

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
