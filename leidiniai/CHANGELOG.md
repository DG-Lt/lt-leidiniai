# Changelog

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
