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
| IKI | https://iki.lt/leidiniai/ → block `.page-content.publications`: `h2.title` ("IKI Kainų leidinys Nr. 47"), `.date-block` ("Pasiūlymai galioja 2026 11 16 - 2026 11 22"), button "ATSIŲSTI LEIDINĮ" → PDF. File names change: `B47-bazinis_www.pdf` (2026-11-13), corrected `IKI-Nr_47-2026-11-16-11-22-d-koreguotas.pdf` (re-uploaded 2026-11-18). "Kiti IKI leidiniai" → sub-pages `/leidiniai/<slug>/` with the same block (store offers "Specialūs pasiūlymai …" per store, wine catalogue undated). **Footer links policy PDFs – not leaflets** (checked 2026-11-20). PDF: InDesign, text layer, 65 pages A4, ~48 MB. Viewer is Issuu — not needed | PDF text + page render crops | Weekly Mon–Sun (Nr. 47: 2026-11-16 … 11-22); PDF uploaded the Friday before, may be replaced mid-week |
| Lidl | https://www.lidl.lt/c/kainu-leidiniai/s10020254 → links `/l/lt/leidinys/maisto-prekiu-pasiulymai-YYYYMMDD-kwNN-pr/...` (food) and `ne-maisto-...` (non-food). JSON `https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=<id>&region_id=0&region_code=0` → `flyer.pdfUrl`, `hiResPdfUrl`, `startDate`, `endDate`, `offerStartDate`, `offerEndDate`, `pages[]` (image, zoom, width, height, keyWords, altText); `products` empty. PDF has a text layer (36 pages, 14.7 MB) | JSON for dates/pages, PDF for products | Weekly Mon–Sun; next week online by Saturday |
| Norfa | https://www.norfa.lt/leidiniai/ → "Atsisiųsti leidinį" `https://www.norfa.lt/leidiniai/download/1` (PDF `Norfa523-Web2.pdf`, text layer, 24 pages, 14.8 MB). Viewer = Yumpu embed | PDF | Every 2 weeks, Thu–Wed (Nr. 23 (523): 2026-11-12 … 11-25) |
| Maxima | https://www.maxima.lt/leidiniai → iPaper (page images only). **Use https://www.maxima.lt/pasiulymai**: 116 offer cards (`[data-controller=offerCard]`, `data-offercard-offer-id` — numeric until 2026-11-19, **UUIDs since 2026-11-20** (160 cards, new sections "Buitinė chemija", "Konditerija", "Prekės gyvūnams"; `__meta-shop` = only in some stores), `data-categories-multiple`), section `h2` = category; classes `offer-price-tag__price-integer` / `__price-fraction`, `__old-price`, `__bottom-discount` or `__discount-value`, `__meta-comparison` ("1 kg – 2,36 €"), `__meta-date` ("Iki 11.16"), `__icon img[alt]` ("Tik su AČIŪ kortele"); images `offers.maxima.lt/media/MarketingOffer/*.png`; per-offer HTML `/webservices/marketing-offers/general/<id>?locale=lt` | Offers page, no OCR | Weekly Tue–Mon; weekend offers Thu–Mon |
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

## Site check 2026-11-19 (for the app fetchers)
- **IKI**: iki.lt answered the cloud browser with a Cloudflare "Just a moment…" challenge. From the home IP it worked in a normal browser (prototype). The app tries a plain request, then headless Chromium; it never solves CAPTCHAs. If both are blocked, the run reports the problem.
- **Lidl**: listing has Savaitės pasiūlymai (food `…-kw47-pr`, non-food `…-kw47`), catalogues (`maisto-idejos-kaledoms-2026`, `zaislai-2026`, `pasiulymas-lidliukams-2025kw18`), a store leaflet (`bajoru-kel-6-visoriai-kw47`) and alcohol (`skoniu-atradimai-2026-lapkritis`). API pages have `type` STANDARD / PROMOTION (comparison ads, no products) and `keyWords` per page; `startDate` = publish day, `offerStartDate/offerEndDate` = validity.
- **Norfa**: one leaflet, text "NORFA Nr. 23 (523)" + "2026.11.12 - 2026.11.25"; download button is JS (`/leidiniai/download/1` from the prototype).
- **Maxima**: /pasiulymai unchanged (offer cards, "Iki 11.23", "1 kg – 3,38 €", "Tik su AČIŪ kortele" icon, "3 vnt. už", "1+1", "nuo XX" store formats).
- **Rimi**: listing page is https://www.rimi.lt/asortimentas/rimi-savaitinis-leidinys → weekly `2026/weekly/rimi-savaitinis-leidinys-nr-47/` plus catalogues under `2026/other/…` and `2026/alko/…`. leidiniai.rimi.lt root has no index.
- **Šilas**: now Nr. 23 (2026-11-18 … 12-01), 12 pages; the page links one JPEG per page (`SLS23_01.jpg` …) and `SILAS_Nr23_2026.pdf`.

## Parsers in the app (step 3, 2026-11-19) — `leidiniai/app/leidiniai/parsers/`
Checked page by page against the week 46/47 files; regression pages in `tests/fixtures/` (local only, not committed – shop material; built by `tests/make_fixtures.py`).
- **Layout rule (IKI, Lidl, Norfa):** product text is always left of or above its own price. Text blocks go to
  the price with the lowest cost; prices wholly left of / above a block pay `(distance + 25) × penalty`
  (Lidl 3/3, Norfa 3/2, IKI left 3 / above 10). IKI prints the name above the photo and the price below it
  (up to ~200 pt apart), so far links need the block and the price to share a column.
- **Unit prices** ("1 kg = 5,98 €", "9,45 Eur/kg") are recognised before old prices: the prototype read most
  Lidl/IKI unit prices as old prices.
- **IKI:** badge numbers are set digit by digit ("4" "8" "%") → touching same-size digits are joined; "1+1"/"2+1"
  badges have a drawn plus sign (two big digits ~16 pt apart); "SUTAUPOTE x" under multi-buy prices is the
  saving, not an old price; green hearts "TIK ♥♥♥" are pictures (card/app price not detected yet).
- **Lidl:** headline text up to 12.6 pt; 5–7 digit product code ends a text block and is the product id;
  "PERKANT 1 VNT. 1,39" + "Antram su Lidl Plus -68% 0,45" = one offer (single price kept with it).
- **Norfa:** a few cells hold two products with one price; "Su pipirais" variants under a price can attach to
  the neighbour.
- Rotated/tracked lettering comes out letter by letter → non-upright characters dropped, runs of single letters removed.
- **Maxima** (116 cards): all carry "Tik su AČIŪ kortele"; forms: price + old + "-NN%", discount-only
  (category offers, `discount-value`), "2 vnt. už"/"3 vnt. už"/"1+1" benefit, "nuo" label; unit "1 kg – x €"
  or "1 kg ≤ x €"; dates "Iki 11.16" / "Iki 12.07".
- **Rimi** e-shop card text forms: leading "3 49 € 23,27 €/kg" = card (Mano Rimi) price with the shelf price
  "4.49 € už vnt." after the name; "… 2.87 € už vnt. … Įprasta kaina: 3,59 €" = general discount; "Šiuo metu
  prekės nėra" = not available. Hotspots with many codes (brand offers) list up to 40 products: all are kept
  (792 products from 217 lookups). The leading price being the Mano Rimi price is an assumption from the
  e-shop layout.
- Rimi `SH-` codes (inferred from product names): 1 alcohol (incl. non-alcoholic beer mixes), 2 pantry (broad),
  3 bakery, 4 drinks, 5 pets, 6 hygiene, 7 baby, 8 flowers, 9 meat/fish/ready meals (broad), 10 household,
  11 dairy, 12 sweets, 13 frozen, 14 toys/home, 15 fruit & veg, 19 pantry, 20 sweets, 77 plant-based spreads.
- Results on the full files: Lidl 233 offers (232 named, 180 unit prices, 54 Lidl Plus), Norfa 345
  (334 with a real name, 237 old prices), IKI 445 (422 named, 146 brand/category badges), Maxima 116, Rimi 792.
  Parse + crops: IKI 65 pages ≈ 40 s, Lidl ≈ 5 s, Norfa ≈ 10 s on this test machine; crops ≈ 26 MB per week.
- Categories: shop category when it is specific, else a Lithuanian stem dictionary on the head noun (the last
  matching word of the name's first phrase), else a broad shop category, else "Kita". Unsorted on the test
  files: Lidl 14/233, Norfa 54/345, IKI 58/445.
