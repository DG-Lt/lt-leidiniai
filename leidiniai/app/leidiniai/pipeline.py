"""What happens after a leaflet is downloaded. Step 2: nothing yet but marking image-only leaflets.
Step 3 plugs the parsers in here."""
from __future__ import annotations


def after_download(conn, settings, issue_id, info, summary, log) -> None:
    if info.parser == "vision":
        with conn:
            conn.execute("UPDATE issues SET status='waiting_parser' WHERE id=?", (issue_id,))
        log.info("%s %s: image-only leaflet, waits for the vision parser (later step)", info.chain, info.key)
