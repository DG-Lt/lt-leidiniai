import sys, json, re, os, html
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from generic import parse
from bs4 import BeautifulSoup
import pypdfium2 as pdfium
D=(sys.argv[1].rstrip('/')+'/') if len(sys.argv)>1 else 'data/'
OUT=sys.argv[2] if len(sys.argv)>2 else 'out'; os.makedirs(OUT+'/img',exist_ok=True)
items=[]
def r2(x): return round(x,2) if isinstance(x,float) else x

# --- text-layer PDFs
cfg=[('Lidl',D+'MAISTO-PREKIU-PASIULYMAI-Nuo-lapkricio-16-d-00.pdf',dict(price_min=40,old_rng=(9,11),disc_min=15,text_max=10.5,maxd=90,card_words=('Lidl Plus',))),
     ('Norfa',D+'Norfa523-Web2.pdf',dict(price_min=20,old_rng=(8,12),disc_min=11,text_max=8.5,maxd=90,card_words=('kortel',))),
     ('IKI',D+'B47-bazinis_www.pdf',dict(price_min=25,old_rng=(9,16),disc_min=40,text_max=13.5,maxd=110,card_words=('kortel',)))]
for chain,path,kw in cfg:
    its=parse(path,chain,**kw)
    pdf=pdfium.PdfDocument(path); cache={}
    for n,it in enumerate(its):
        p=it['page']-1
        if p not in cache: cache[p]=pdf[p].render(scale=2).to_pil().convert('RGB')
        im=cache[p]; c=it.pop('crop'); it.pop('bbox')
        box=[max(0,int((c['x0']-6)*2)),max(0,int((c['top']-6)*2)),min(im.width,int((c['x1']+6)*2)),min(im.height,int((c['bottom']+6)*2))]
        fn=f'img/{chain}_{it["page"]:02d}_{n:03d}.jpg'
        if box[2]-box[0]>10 and box[3]-box[1]>10: im.crop(box).save(OUT+'/'+fn,quality=80); it['img']=fn
        it['price']=r2(it['price']); it['old_price']=r2(it['old_price'])
        it['source']=os.path.basename(path)
    items+=its
    print(chain,len(its))

# --- Maxima offers page
s=BeautifulSoup(open(D+'maxima_pasiulymai.html',encoding='utf-8').read(),'lxml')
cat=None; mx=0
for el in s.select('h2, [data-controller="offerCard"]'):
    if el.name=='h2': cat=el.get_text(strip=True); continue
    g=lambda cls:(el.select_one('.'+cls).get_text(' ',strip=True) if el.select_one('.'+cls) else None)
    i,f=g('offer-price-tag__price-integer'),g('offer-price-tag__price-fraction')
    price=float(f'{i}.{f}') if i and f else None
    old=g('offer-price-tag__old-price'); disc=g('offer-price-tag__bottom-discount') or (('-'+g('offer-price-tag__discount-value')+'%') if g('offer-price-tag__discount-value') else None)
    icon=el.select_one('.offer-price-tag__icon img')
    items.append(dict(chain='Maxima',page=None,kind='offer',name=el.select_one('h4').get_text(' ',strip=True),price=price,
        old_price=float(old.replace('€','').replace(',','.').strip()) if old else None,discount=disc,
        unit_price=g('offer-price-tag__meta-comparison'),valid=g('offer-price-tag__meta-date'),
        card=(icon['alt'] if icon else None),category=cat,img=el.select_one('img')['src'],source='maxima.lt/pasiulymai'))
    mx+=1
print('Maxima',mx)

# --- Rimi: enrichments + e-shop
enr=json.load(open(D+'rimi_nr46_enrichments.json')); shop=json.load(open(D+'rimi_nr46_eshop.json'))
import urllib.parse as up
rc=0; seen=set()
for e in enr['enrichments']:
    q=up.parse_qs(up.urlparse(e['url']).query)['query'][0]
    prods=shop.get(q) or []
    if not isinstance(prods,list) or not prods: continue
    for p in prods[:1] if len(prods)==1 else prods[:3]:
        g=p['gtm']; 
        if g.get('id') in seen: continue
        seen.add(g.get('id'))
        t=p['text']; m=re.match(r'(\d+) (\d\d) €',t)
        now=float(f'{m.group(1)}.{m.group(2)}') if m else None
        reg=g.get('price')
        items.append(dict(chain='Rimi',page=e['p']+1,kind='hotspot',name=g.get('name'),price=now,old_price=reg if now and reg and reg>now else None,
            discount=(f"-{round((1-now/reg)*100)}%" if now and reg and reg>now else None),unit_price=None,card=None,category=g.get('category'),
            img=p['img'],group=len(prods),source='leidiniai.rimi.lt + e-shop'))
        rc+=1
print('Rimi',rc)
json.dump(items,open(OUT+'/items.json','w'),ensure_ascii=False,indent=1)
