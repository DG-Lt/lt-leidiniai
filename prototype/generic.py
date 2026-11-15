import re, pdfplumber
from pdfparse import *
UNIT_RE=re.compile(r'(?:1\s*(kg|l|vnt\.?)\s*[=≤–-]\s*([\d,]+)\s*€)|(?:([\d,]+)\s*Eur/(kg|l|vnt))',re.I)
QTY_RE=re.compile(r'^(\d+\s*x\s*)?[\d,–-]+\s*(g|kg|ml|l|vnt\.?)[,.]?$',re.I)
def num(s):
    try: return float(s.replace(',','.'))
    except: return None

def money_tokens(ws, smin, smax):
    """Assemble prices from 'euros' + superscript 'cents' tokens or 'x,yy' tokens within a font-size range."""
    out=[]; used=set()
    cand=[w for w in ws if smin<=w['size']<=smax and re.fullmatch(r'\d{1,3}(,\d\d)?',w['text'])]
    for i,w in enumerate(cand):
        if id(w) in used: continue
        if ',' in w['text']:
            out.append(dict(x0=w['x0'],x1=w['x1'],top=w['top'],bottom=w['bottom'],value=num(w['text']),size=w['size'])); continue
        # cents token: smaller, right next to it, top aligned
        cents=[c for c in ws if c is not w and re.fullmatch(r'\d\d',c['text']) and c['size']<w['size']*0.95 and c['size']>=w['size']*0.45
               and w['x1']-15<=c['x0']<=w['x1']+20 and abs(c['top']-w['top'])<w['size']*0.5]
        if cents:
            c=min(cents,key=lambda c:abs(c['x0']-w['x1'])); used.add(id(c))
            out.append(dict(x0=w['x0'],x1=c['x1'],top=min(w['top'],c['top']),bottom=max(w['bottom'],c['bottom']),value=int(w['text'])+int(c['text'])/100,size=w['size']))
    return out, used

def discount_tokens(ws, smin):
    out=[]; used=set()
    for w in ws:
        if w['size']<smin: continue
        if re.fullmatch(r'-\d{1,2}%',w['text']) or re.fullmatch(r'\d\+\d',w['text']):
            out.append(dict(x0=w['x0'],x1=w['x1'],top=w['top'],bottom=w['bottom'],text=w['text'])); used.add(id(w)); continue
        if re.fullmatch(r'\d{1,2}',w['text']):
            pc=[p for p in ws if p['text']=='%' and w['x1']-5<=p['x0']<=w['x1']+40 and abs(p['top']-w['top'])<w['size']]
            if pc:
                p=pc[0]; used|={id(w),id(p)}
                mn=[m for m in ws if m['text'] in '-–' and m['x1']<=w['x0']+3 and w['x0']-m['x1']<30 and abs(m['top']-w['top'])<w['size']]
                for m in mn: used.add(id(m))
                out.append(dict(x0=min([w['x0']]+[m['x0'] for m in mn]),x1=p['x1'],top=w['top'],bottom=w['bottom'],text='-'+w['text']+'%'))
    return out, used

def parse(path, chain, price_min, old_rng, disc_min, text_max, maxd=90, pages=None, card_words=()):
    pdf=pdfplumber.open(path); items=[]
    for pi,pg in enumerate(pdf.pages):
        if pages is not None and pi not in pages: continue
        ws=dedupe(words(pg))
        disc,du=discount_tokens(ws,disc_min)
        ws2=[w for w in ws if id(w) not in du]
        prices,pu=money_tokens(ws2,price_min,200)
        olds,ou=money_tokens([w for w in ws2 if id(w) not in pu],*old_rng)
        used=du|pu|ou
        # words consumed by price assembly (euros tokens)
        consumed=set()
        for w in ws2:
            for p in prices+olds:
                if p['x0']-1<=w['x0']<=p['x1']+1 and abs(w['top']-p['top'])<p['size']*0.6 and re.fullmatch(r'[\d,]+',w['text']) and w['size']>=min(old_rng[0],price_min*0.4): consumed.add(id(w))
        rest=[w for w in ws if id(w) not in used|consumed and w['size']<=text_max]
        bl=[dict(b,kind='block') for b in blocks(lines(rest,text_max))]
        # anchors: prices; discount badges with no price nearby become anchors too (category offers)
        anchors=[dict(p,kind='price') for p in prices]
        for d in disc:
            if not any(bbox_dist(d,a)<70 for a in anchors): anchors.append(dict(d,kind='badge',value=None))
        things=[dict(o,kind='old') for o in olds]+[dict(d,kind='disc') for d in disc if not any(a is d or (a['kind']=='badge' and a['x0']==d['x0'] and a['top']==d['top']) for a in anchors)]
        A=assign(anchors,things,70)
        B=assign(anchors,bl,maxd)
        imgs=page_images(pg)
        for i,a in enumerate(anchors):
            lines_=[l for b in sorted(B[i],key=lambda b:(b['top'],b['x0'])) for l in b['lines']]
            txt=[l['text'] for l in lines_]; joined=' '.join(txt)
            m=UNIT_RE.search(joined)
            unit=None
            if m: unit=(m.group(2)+' €/'+m.group(1)) if m.group(1) else (m.group(3)+' €/'+m.group(4))
            old=[t for t in A[i] if t['kind']=='old']; dd=[t for t in A[i] if t['kind']=='disc']
            name=' '.join(t for t in txt if not UNIT_RE.fullmatch(t.strip()) and not re.fullmatch(r'\d{5,8}.*',t))
            box=union([a]+A[i]+B[i])
            near=[im for im in imgs if bbox_dist(box,im)<30]
            items.append(dict(chain=chain,page=pi+1,kind=a['kind'],price=a.get('value'),old_price=old[0]['value'] if old else None,
                 discount=(a['text'] if a['kind']=='badge' else (dd[0]['text'] if dd else None)),
                 name=name.strip(), unit_price=unit, card=any(c.lower() in joined.lower() for c in card_words) or None,
                 bbox=box, crop=union([box]+near) if near else box))
    return items
