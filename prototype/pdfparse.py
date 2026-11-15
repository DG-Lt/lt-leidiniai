import pdfplumber, re, math, json, sys
PRICE_RE = re.compile(r'^\d{1,3}([,.]\d{2})?$')

def words(page):
    ws = page.extract_words(extra_attrs=['size'], keep_blank_chars=False, use_text_flow=False)
    for w in ws: w['size']=round(w['size'],1)
    return ws

def dedupe(ws):
    # Lidl draws headline text 2-3 times with tiny offsets (shadow); drop near duplicates
    out=[]
    for w in ws:
        if any(o['text']==w['text'] and abs(o['x0']-w['x0'])<3 and abs(o['top']-w['top'])<3 for o in out): continue
        out.append(w)
    return out

def lines(ws, maxsize):
    # merge small words into lines
    sm=[w for w in ws if w['size']<=maxsize]
    sm.sort(key=lambda w:(round(w['top']),w['x0']))
    L=[]
    for w in sm:
        for l in L:
            if abs(l['top']-w['top'])<2 and 0<=w['x0']-l['x1']<8 and abs(l['size']-w['size'])<0.6:
                l['text']+=' '+w['text']; l['x1']=w['x1']; l['bottom']=max(l['bottom'],w['bottom']); break
        else: L.append(dict(text=w['text'],x0=w['x0'],x1=w['x1'],top=w['top'],bottom=w['bottom'],size=w['size']))
    return L

def blocks(L, gap=6, xtol=6):
    L=sorted(L,key=lambda l:(l['top'],l['x0']))
    B=[]
    for l in L:
        for b in B:
            last=b['lines'][-1]
            if abs(last['x0']-l['x0'])<xtol and 0<=l['top']-last['bottom']<gap:
                b['lines'].append(l); b['x0']=min(b['x0'],l['x0']); b['x1']=max(b['x1'],l['x1']); b['bottom']=l['bottom']; break
        else: B.append(dict(lines=[l],x0=l['x0'],x1=l['x1'],top=l['top'],bottom=l['bottom']))
    return B

def bbox_dist(a,b):
    dx=max(0,max(a['x0'],b['x0'])-min(a['x1'],b['x1']))
    dy=max(0,max(a['top'],b['top'])-min(a['bottom'],b['bottom']))
    return math.hypot(dx,dy*1.3)

def union(items):
    return dict(x0=min(i['x0'] for i in items),x1=max(i['x1'] for i in items),top=min(i['top'] for i in items),bottom=max(i['bottom'] for i in items))

def assign(anchors, things, maxd):
    out={i:[] for i in range(len(anchors))}
    for t in things:
        d=[(bbox_dist(a,t),i) for i,a in enumerate(anchors)]
        if not d: continue
        dm,i=min(d)
        if dm<=maxd: out[i].append(t)
    return out

def page_images(page):
    W,H=page.width,page.height
    imgs=[]
    for im in page.images:
        x0,x1,top,bottom=max(0,im['x0']),min(W,im['x1']),max(0,im['top']),min(H,im['bottom'])
        if x1-x0<15 or bottom-top<15: continue
        if (x1-x0)*(bottom-top) > 0.35*W*H: continue  # background
        imgs.append(dict(x0=x0,x1=x1,top=top,bottom=bottom))
    return imgs
