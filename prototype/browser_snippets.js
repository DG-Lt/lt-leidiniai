// Snippets used in a browser console for prototype 1 (2026-11-15).
// The add-on will do the same in Python; these document what was fetched and how.

// 1) On https://www.maxima.lt/pasiulymai : save the rendered page.
(() => {
  const html = '<!-- ' + location.href + ' -->\n' + document.documentElement.outerHTML;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
  a.download = 'maxima_pasiulymai.html';
  a.click();
})();

// 2) On the Rimi leaflet page (https://leidiniai.rimi.lt/<year>/weekly/rimi-savaitinis-leidinys-nr-NN/),
//    after it has loaded: save the iPaper enrichments (hotspots with e-shop product codes).
(async () => {
  const u = performance.getEntriesByType('resource').map(e => e.name).find(u => /Enrichments/.test(u));
  const j = await (await fetch(u)).json();
  const out = {
    source: location.href, title: document.title, enrichmentsUrl: u,
    enrichments: j.enrichments.map(e => ({ p: e.pageIndex, x: e.x, y: e.y, w: e.width, h: e.height, url: e.url, type: e.type })),
  };
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out)], { type: 'application/json' }));
  a.download = 'rimi_nrNN_enrichments.json';
  a.click();
})();

// 3) On any https://www.rimi.lt/e-parduotuve/... page: look up each hotspot query in the e-shop
//    (250 ms apart) and save the product cards. Q = list of the "query" values from step 2.
(async (Q) => {
  const parse = (html) => {
    const d = new DOMParser().parseFromString(html, 'text/html');
    return [...d.querySelectorAll('[data-gtm-eec-product]')].map(c => {
      let g = {}; try { g = JSON.parse(c.getAttribute('data-gtm-eec-product')); } catch (e) {}
      const card = c.closest('.card') || c;
      return { gtm: g, text: (card.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 300),
               img: (card.querySelector('img') || {}).src || null };
    });
  };
  const res = {};
  for (const q of Q) {
    try { res[q] = parse(await (await fetch('/e-parduotuve/lt/paieska?query=' + encodeURIComponent(q))).text()); }
    catch (e) { res[q] = { error: String(e) }; }
    await new Promise(r => setTimeout(r, 250));
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(res)], { type: 'application/json' }));
  a.download = 'rimi_nrNN_eshop.json';
  a.click();
})([/* queries */]);
