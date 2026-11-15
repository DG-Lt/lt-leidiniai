# Findings and design (2026-11-15)

Goal: collect the weekly / biweekly discount leaflets of IKI, Rimi, Maxima, Norfa, Lidl and Šilas, extract products (name, price, old price, discount, unit price, validity, photo crop), categorise, keep history, show in Home Assistant. Fully local: **no Anthropic or other cloud AI API**.

## Decisions
- Runs as **one Home Assistant add-on** on the HA laptop (ThinkPad X280, i5-8350U 4C/8T, 15.4 GB RAM, ~12 GB free, 373 GB free disk). Web UI as an HA sidebar panel (ingress) + HA sensors (new leaflet, watched items on sale). The Synology DS918+ (Celeron J3455, no AVX) is not used for processing.
- Lithuanian kept as printed (UTF-8). Each name also gets a plain-letter key (ą→a, š→s…, lower case) for search, keyword categorising, watch list and cross-chain matching.
- Processing only once per new leaflet, at night; heavy steps at low priority, 2–3 threads.
- Next check per chain = about 2 days before the current issue's end date, then daily until the next issue appears (no fixed daily processing).
- **Logs:** rotating log files in the add-on data folder (per run: chain, issue, items found, warnings, errors, timings) and a **"Download logs"** button in the web UI (zip of logs + last run summaries), so they can be handed to Claude for debugging.
- Deploy as a **local add-on**: this repo cloned into HA `/addons` via the SSH add-on; update = `git pull` + Rebuild (the add-on store can't easily use a private repo).

## How each chain publishes (checked in the browser 2026-11-15)
| Chain | Source | Extraction | Cycle |
|---|---|---|---|
| IKI | https://iki.lt/leidiniai/ → PDF e.g. `https://iki.lt/wp-content/uploads/2026/11/13/B47-bazinis_www.pdf` (InDesign, text layer, 65 pages A4, 48.7 MB). Viewer is Issuu — not needed | PDF text + page render crops | Weekly Mon–Sun (Nr. 47: 2026-11-16 … 11-22); PDF uploaded the Friday before |
| Lidl | https://www.lidl.lt/c/kainu-leidiniai/s10020254 → links `/l/lt/leidinys/maisto-prekiu-pasiulymai-YYYYMMDD-kwNN-pr/...` (food) and `ne-maisto-...` (non-food). JSON `https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=<id>&region_id=0&region_code=0` → `flyer.pdfUrl`, `hiResPdfUrl`, `startDate`, `endDate`, `offerStartDate`, `offerEndDate`, `pages[]` (image, zoom, width, height, keyWords, altText); `products` empty. PDF has a text layer (36 pages, 14.7 MB) | JSON for dates/pages, PDF for products | Weekly Mon–Sun; next week online by Saturday |
| Norfa | https://www.norfa.lt/leidiniai/ → "Atsisiųsti leidinį" `https://www.norfa.lt/leidiniai/download/1` (PDF `Norfa523-Web2.pdf`, text layer, 24 pages, 14.8 MB). Viewer = Yumpu embed | PDF | Every 2 weeks, Thu–Wed (Nr. 23 (523): 2026-11-12 … 11-25) |
| Maxima | https://www.maxima.lt/leidiniai → iPaper (page images only). **Use https://www.maxima.lt/pasiulymai**: 116 offer cards (`[data-controller=offerCard]`, `data-offercard-offer-id`, `data-categories-multiple`), section `h2` = category; classes `offer-price-tag__price-integer` / `__price-fraction`, `__old-price`, `__bottom-discount` or `__discount-value`, `__meta-comparison` ("1 kg – 2,36 €"), `__meta-date` ("Iki 11.16"), `__icon img[alt]` ("Tik su AČIŪ kortele"); images `offers.maxima.lt/media/MarketingOffer/*.png`; per-offer HTML `/webservices/marketing-offers/general/<id>?locale=lt` | Offers page, no OCR | Weekly Tue–Mon; weekend offers Thu–Mon |
| Rimi | `https://leidiniai.rimi.lt/2026/weekly/rimi-savaitinis-leidinys-nr-46/` (iPaper). Enrichments JSON `cdn.ipaper.io/iPaper/Papers/<guid>/Enrichments/v1/.../Page1-42.json?token=…` (230 hotspots: `pageIndex`, `x`, `y`, `width`, `height`, `url` = `https://www.rimi.lt/e-parduotuve/lt/paieska?query=<codes>`, some URLs truncated). E-shop search HTML: `[data-gtm-eec-product]` JSON (id, name, category e.g. `SH-15-1-17`, regular price) + card text with current price + image `rimibaltic-res.cloudinary.com/.../MAT_<id>_PCE_LT` | Enrichments → e-shop lookup (≈217 requests, 250 ms apart). Caution: e-shop price may differ from leaflet / card price | Weekly Tue–Mon (Nr. 46: 2026-11-10 … 11-16) |
| Šilas | https://www.silas.lt/akcijos/ → `https://www.silas.lt/wp-content/uploads/2026/10/SILAS_Nr22_8psl.pdf` — **image-only** (8 pages, one 992×1404 JPEG each) | Local vision model (Qwen2.5-VL 7B via Ollama); Tesseract alone not enough | Every 2 weeks, Wed–Tue (Nr. 22: 2026-11-04 … 11-17), published Wednesday |

## Prototype 1 (2026-11-15) — `prototype/`
Python: pdfplumber words with font size + pypdfium2 page renders; BeautifulSoup for Maxima.
- PDFs: price = large-font token ("1,99", or euros + smaller superscript cents token "1"+"29"); discount badge = "-NN%" or "NN"+"%" (+"-"); old price = mid-size price token; small text lines grouped into blocks and assigned to the nearest price anchor; crop = page render of anchor + text + nearest images. Lidl draws headlines 2–3× (shadow) → words de-duplicated.
- Font sizes: Lidl price ≥ 40, old 9–11, discount ≥ 15, text ≤ 10.5 (7-digit product code in the text). Norfa price ≥ 20 (euros 33 + cents 23), old 8–12 (9.4), discount ≥ 11, text ≤ 8.5, "Tik" marker 16. IKI price ≥ 25 (euros 46 + cents 28), old 9–16 ("Įprasta kaina" 14/9), discount badge digits 58.8 + "%" 20.6 + "-" 43, text ≤ 13.5; IKI has many category offers ("-40 %" for a brand, no price).
- Results: Lidl 236 rows (229 named, 235 priced, old price only 60); Norfa 345 (298 priced, 237 old); IKI 445 (256 priced, 189 badge-only); Maxima 116 (exact); Rimi 416 products from 217 hotspots (268 with current < regular price).
- Šilas: Tesseract (eng+pol in the test, `lit` not available there) reads names and "1 kg – x €" roughly, **not** the big stylised prices → vision model needed.
- To tune: name blocks sometimes merged with a neighbour; crops too generous (include the neighbour's photo); Lidl/Norfa old price on some pages; float rounding.

## Categorising
Maxima and Rimi provide their own categories. Others: Lithuanian keyword dictionary on the plain-letter key, then multilingual-e5-small against Lithuanian category names; corrections in the UI feed the dictionary.

## Next steps
1. Tune parsers per chain; add Šilas via Ollama + Qwen2.5-VL.
2. Build the add-on: fetchers, scheduler, SQLite, web panel (ingress), HA sensors, logs download.
