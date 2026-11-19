# Leidiniai

Collects the discount leaflets of IKI, Rimi, Maxima, Norfa, Lidl and Šilas, extracts the offers and keeps their price history. Everything runs locally on this machine; no cloud AI.

Open the **Leidiniai** panel in the sidebar. Options are explained in the Configuration tab.

## Panel
- **Pasiūlymai** – the offers valid now (or starting soon): search without Lithuanian letters
  ("sviest" finds "Sviestas"), filter by chain and category, sort by discount, price or unit price.
  Click an offer for its price history, the same product in other chains and the category correction.
  "Įsiminti raktažodį" (remember keyword) teaches the category dictionary; all products not set by hand are
  then sorted again.
- **Stebimi** – the watch list: words to look for in every new leaflet, with the matching offers.
- **Leidiniai** – leaflets found, their state, the last checks and a "check now" button.

Offers are read from the leaflet as printed. Some cells of a leaflet are hard to read automatically:
an offer without a name shows its picture so you can still see it. Rimi prices come from the Rimi e-shop
and can differ from the paper leaflet.

Install and update steps: see `docs/install.md` in the repository.
