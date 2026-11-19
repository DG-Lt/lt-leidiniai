# lt-leidiniai

Collects the discount leaflets (akcijų leidiniai) of Lithuanian supermarket chains — **IKI, Rimi, Maxima, Norfa, Lidl, Šilas** — extracts every offer (name, price, old price, discount, unit price, validity, product picture), categorises it and keeps the history. Runs locally as a Home Assistant add-on; no cloud AI.

Status: **in development** (app built in steps, see the pull requests). Design and per-chain findings: [docs/findings.md](docs/findings.md).

## Repository layout
| Path | What |
|---|---|
| `repository.yaml` | Makes the clone a Home Assistant app repository (local apps) |
| `leidiniai/` | The Home Assistant app: `config.yaml`, `Dockerfile`, Python package in `app/leidiniai/` |
| `tests/` | pytest tests (`pip install -r requirements-dev.txt`, then `pytest`) |
| `docs/findings.md` | How each chain publishes its leaflet, decisions, prototype results |
| `prototype/` | First extraction test (Python) on the week 46/47 leaflets |

## Running the panel locally
```
pip install -r requirements-dev.txt
cd leidiniai/app
LEIDINIAI_DEV=1 LEIDINIAI_DATA=/tmp/leidiniai python -m leidiniai   # http://localhost:8099
```
`LEIDINIAI_DEV=1` turns off the ingress-only check.

## Running the prototype
Needs Python 3.11+ and `pip install -r prototype/requirements.txt`.

1. Put the current files in one folder (e.g. `data/`): the IKI, Lidl and Norfa PDFs, `maxima_pasiulymai.html` (saved page of https://www.maxima.lt/pasiulymai), `rimi_nr46_enrichments.json` and `rimi_nr46_eshop.json` (made in the browser with `prototype/browser_snippets.js`). The file names are set at the top of `prototype/run.py`.
2. `python prototype/run.py data out` → `out/items.json` and product crops in `out/img/`.

Downloaded leaflets and outputs are not committed (`.gitignore`).
