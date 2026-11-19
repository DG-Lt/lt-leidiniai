# Project rules

- Fully local processing: no Anthropic or other cloud AI API in the app. Local OCR (Tesseract with `lit`), local vision model (Ollama) only where a chain publishes images only.
- Keep Lithuanian text exactly as printed (UTF-8). Add a plain-letter key (ą→a, č→c, ę→e, ė→e, į→i, š→s, ų→u, ū→u, ž→z, lower case) for search and matching; never store only the folded form.
- Be gentle with the shops' sites: one check per chain when a new issue is due, requests spaced out, no parallel hammering.
- Every run logs chain, issue, counts, warnings, errors and timings to rotating files; the web UI offers a "Download logs" zip.
- Target: Home Assistant OS add-on on x86-64 (i5-8350U, 16 GB RAM) shared with HA — heavy steps at night, low priority, 2–3 threads.
- Update `docs/findings.md` when a chain changes how it publishes.
- The app is installed from this public repository via the HA app store: every change under `leidiniai/` that reaches `main` bumps `version` in `leidiniai/config.yaml` and gets a `CHANGELOG.md` entry, otherwise the box never sees it. No secrets or personal data in the repo.
- One PR per step, based on `main` (no stacked PRs).
