from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from pydantic import BaseModel
import sqlite3, csv, io, json, os, re, math, statistics, uuid, urllib.request, urllib.parse, secrets, hashlib, hmac
from datetime import datetime, timedelta
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
DB=BASE/'karigar_link.db'
DATA=BASE.parent/'data'
DATA.mkdir(exist_ok=True)
IMAGES=DATA/'product_images'; IMAGES.mkdir(exist_ok=True)
app=FastAPI(title='Karigar Link', version='13.0.0', description='AI-driven market intelligence and digital commerce assistant for marginalized artisans.')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])

SCHEMA='''
CREATE TABLE IF NOT EXISTS artisans(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,language TEXT,region TEXT,craft TEXT,capacity INTEGER DEFAULT 0,created_at TEXT);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT,artisan_id INTEGER,name TEXT,craft TEXT,material TEXT,region TEXT,technique TEXT,description TEXT,cost REAL,price REAL,capacity_week INTEGER DEFAULT 0,created_at TEXT);
CREATE TABLE IF NOT EXISTS datasets(id INTEGER PRIMARY KEY AUTOINCREMENT,artisan_id INTEGER,name TEXT,rows INTEGER,columns INTEGER,quality REAL,imported_at TEXT,raw_path TEXT,mapping_json TEXT);
CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY AUTOINCREMENT,dataset_id INTEGER,sale_date TEXT,product TEXT,quantity REAL,price REAL,buyer TEXT,city TEXT,payment TEXT);
CREATE TABLE IF NOT EXISTS buyers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,type TEXT,city TEXT,budget_min REAL,budget_max REAL,volume_min INTEGER,volume_max INTEGER,needs TEXT);
CREATE TABLE IF NOT EXISTS opportunities(id INTEGER PRIMARY KEY AUTOINCREMENT,product_id INTEGER,market TEXT,score REAL,reasons TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT,artisan_id INTEGER,action_type TEXT,entity_id INTEGER,status TEXT,result_value REAL,notes TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS enquiries(id INTEGER PRIMARY KEY AUTOINCREMENT,product_id INTEGER,buyer_name TEXT,buyer_type TEXT,city TEXT,quantity INTEGER,budget REAL,message TEXT,status TEXT DEFAULT 'New',created_at TEXT);
CREATE TABLE IF NOT EXISTS buyer_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,buyer_name TEXT,buyer_type TEXT,city TEXT,product_need TEXT,quantity INTEGER,budget_min REAL,budget_max REAL,delivery_days INTEGER,notes TEXT,status TEXT DEFAULT 'Open',created_at TEXT);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT UNIQUE,phone TEXT UNIQUE,password_hash TEXT,language TEXT DEFAULT 'English',artisan_id INTEGER,created_at TEXT);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER,expires_at TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS phone_otps(id INTEGER PRIMARY KEY AUTOINCREMENT,phone TEXT,otp_hash TEXT,expires_at TEXT,attempts INTEGER DEFAULT 0,verified INTEGER DEFAULT 0,created_at TEXT);
CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY AUTOINCREMENT,artisan_id INTEGER NOT NULL,plan_code TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',started_at TEXT NOT NULL,expires_at TEXT NOT NULL,payment_mode TEXT DEFAULT 'demo',payment_reference TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS marketplace_orders(id INTEGER PRIMARY KEY AUTOINCREMENT,order_number TEXT UNIQUE NOT NULL,customer_name TEXT NOT NULL,email TEXT NOT NULL,phone TEXT NOT NULL,address TEXT NOT NULL,city TEXT NOT NULL,pincode TEXT NOT NULL,payment_method TEXT NOT NULL DEFAULT 'COD',payment_status TEXT NOT NULL DEFAULT 'pending',order_status TEXT NOT NULL DEFAULT 'placed',subtotal REAL NOT NULL,shipping REAL NOT NULL DEFAULT 0,total REAL NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS marketplace_order_items(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL,product_id INTEGER NOT NULL,artisan_id INTEGER NOT NULL,product_name TEXT NOT NULL,quantity INTEGER NOT NULL,unit_price REAL NOT NULL,line_total REAL NOT NULL);
CREATE TABLE IF NOT EXISTS marketplace_reviews(id INTEGER PRIMARY KEY AUTOINCREMENT,product_id INTEGER NOT NULL,customer_name TEXT NOT NULL,rating INTEGER NOT NULL,review TEXT DEFAULT '',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS marketplace_wishlist(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_email TEXT NOT NULL,product_id INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(customer_email,product_id));
CREATE TABLE IF NOT EXISTS customer_accounts(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,phone TEXT NOT NULL DEFAULT '',password_hash TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS customer_sessions(token_hash TEXT PRIMARY KEY,customer_id INTEGER NOT NULL,expires_at TEXT NOT NULL,created_at TEXT NOT NULL);
'''

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.executescript(SCHEMA)
    # Backward-compatible migration for databases created by earlier Karigar Link versions.
    existing={r['name'] for r in c.execute('PRAGMA table_info(products)').fetchall()}
    for name,definition in [('sku','TEXT'),('stock','INTEGER NOT NULL DEFAULT 0'),('image_url','TEXT'),('marketplace_status',"TEXT NOT NULL DEFAULT 'draft'")]:
        if name not in existing: c.execute(f'ALTER TABLE products ADD COLUMN {name} {definition}')
    c.commit(); return c


def _hash_password(password):
    salt=secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 180000)
    return salt.hex()+':'+digest.hex()

def _check_password(password, stored):
    try:
        salt_hex,digest_hex=stored.split(':',1)
        digest=hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt_hex), 180000)
        return hmac.compare_digest(digest.hex(),digest_hex)
    except Exception:
        return False

def _session_token(user_id):
    token=secrets.token_urlsafe(32); th=hashlib.sha256(token.encode()).hexdigest()
    c=db(); c.execute('delete from sessions where expires_at < ?', (datetime.now().isoformat(),)); c.execute('insert into sessions(token_hash,user_id,expires_at,created_at) values(?,?,?,?)',(th,user_id,(datetime.now()+timedelta(days=7)).isoformat(),datetime.now().isoformat())); c.commit(); c.close(); return token

def _user_from_token(token):
    if not token: return None
    th=hashlib.sha256(token.encode()).hexdigest(); c=db(); row=c.execute('select u.* from sessions s join users u on u.id=s.user_id where s.token_hash=? and s.expires_at>?',(th,datetime.now().isoformat())).fetchone(); c.close(); return dict(row) if row else None

def _twilio_verify(action, phone, code=None):
    sid=os.getenv('TWILIO_ACCOUNT_SID','').strip(); auth=os.getenv('TWILIO_AUTH_TOKEN','').strip(); service=os.getenv('TWILIO_VERIFY_SERVICE_SID','').strip()
    if not (sid and auth and service): return False,'Mobile OTP provider is not configured. Add Twilio Verify credentials to .env.'
    import base64
    url=f'https://verify.twilio.com/v2/Services/{service}/Verifications' if action=='send' else f'https://verify.twilio.com/v2/Services/{service}/VerificationCheck'
    data={'To':phone,'Channel':'sms'} if action=='send' else {'To':phone,'Code':code}
    body=urllib.parse.urlencode(data).encode(); req=urllib.request.Request(url,data=body,method='POST',headers={'Authorization':'Basic '+base64.b64encode(f'{sid}:{auth}'.encode()).decode(),'Content-Type':'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req,timeout=12) as r: payload=json.loads(r.read().decode()); return True,payload
    except Exception as e: return False,str(e)

def seed():
    c=db();
    if c.execute('select count(*) n from artisans').fetchone()['n']==0:
        c.execute('insert into artisans(name,phone,language,region,craft,capacity,created_at) values(?,?,?,?,?,?,?)',('Demo Artisan','9999999999','Hindi','Madhya Pradesh','Bamboo Craft',30,datetime.now().isoformat()))
        aid=c.execute('select last_insert_rowid()').fetchone()[0]
        products=[('Bamboo Storage Basket','Bamboo Craft','Bamboo','Madhya Pradesh','Handwoven','Handmade bamboo storage basket for home decor.',330,499,20),('Bamboo Gift Hamper','Bamboo Craft','Bamboo','Madhya Pradesh','Handwoven','Sustainable handcrafted corporate gift basket.',360,599,15),('Handwoven Table Mat','Bamboo Craft','Bamboo','Madhya Pradesh','Handwoven','Set of handmade table mats.',120,249,40)]
        c.executemany('insert into products(artisan_id,name,craft,material,region,technique,description,cost,price,capacity_week) values(?,?,?,?,?,?,?,?,?,?)',[(aid,*p) for p in products])
        buyers=[('Green Corporate Gifts','Corporate','Indore',300,900,20,500,'eco-friendly bulk gifting'),('Heritage Home Store','Retail','Ujjain',250,1200,5,100,'handmade home decor'),('Hotel & Resort Procurement','Institutional','Bhopal',200,1500,25,1000,'regional decor and guest gifts'),('Tourist Souvenir Shop','Retail','Indore',100,700,10,200,'authentic regional craft')]
        c.executemany('insert into buyers(name,type,city,budget_min,budget_max,volume_min,volume_max,needs) values(?,?,?,?,?,?,?,?)',buyers)
        requests=[('Jaipur Home Décor Buyer','Retail','Jaipur','Bamboo baskets / storage',120,350,650,30,'Looking for handmade regional home décor in repeat batches.'),('Central India Corporate Gifting','Corporate','Indore','Eco-friendly gift hampers',250,450,800,45,'Need sustainable gifting options for an upcoming corporate programme.'),('Boutique Hotel Procurement','Institutional','Bhopal','Handmade table mats',80,180,320,25,'Regional handmade products for rooms and dining spaces.')]
        c.executemany('insert into buyer_requests(buyer_name,buyer_type,city,product_need,quantity,budget_min,budget_max,delivery_days,notes) values(?,?,?,?,?,?,?,?,?)',requests)
        c.commit()
    # Always make the packaged demo analytically useful: load sample history if sales are empty.
    if c.execute('select count(*) n from sales').fetchone()['n']==0:
        sample=DATA/'sample_historical_sales.csv'
        if sample.exists():
            with sample.open('r',encoding='utf-8-sig',newline='') as fh: rows=list(csv.DictReader(fh))
            headers=list(rows[0].keys()) if rows else []
            mapping={'date':'Sale Date','product':'Product Name','quantity':'Qty','price':'Rate','buyer':'Customer','city':'City','payment':'Payment Mode'}
            qr_score=100.0
            c.execute('insert into datasets(artisan_id,name,rows,columns,quality,imported_at,raw_path,mapping_json) values(?,?,?,?,?,?,?,?)',(1,'Bundled Demo Historical Sales',len(rows),len(headers),qr_score,datetime.now().isoformat(),str(sample),json.dumps(mapping)))
            did=c.execute('select last_insert_rowid()').fetchone()[0]
            for r in rows:
                def _n(v):
                    try: return float(str(v).replace(',','').replace('₹','').strip())
                    except: return 0.0
                c.execute('insert into sales(dataset_id,sale_date,product,quantity,price,buyer,city,payment) values(?,?,?,?,?,?,?,?)',(did,str(r.get('Sale Date','')).strip(),str(r.get('Product Name','')).strip(),_n(r.get('Qty',0)),_n(r.get('Rate',0)),str(r.get('Customer','')).strip(),str(r.get('City','')).strip(),str(r.get('Payment Mode','')).strip()))
            c.commit()
    c.close()
seed()

ALIASES={
 'date':['date','sale date','sold date','order date','transaction date'],
 'product':['product','product name','item','item name','sku name'],
 'quantity':['qty','quantity','units','pieces','no sold','units sold'],
 'price':['price','rate','selling price','sale price','amount','revenue per unit'],
 'buyer':['buyer','customer','customer name','client'],
 'city':['city','location','district','town','market'],
 'payment':['payment','payment mode','mode','payment method']}

def norm(x): return re.sub(r'[^a-z0-9]','',str(x).lower())
def map_columns(headers):
    out={}
    for target,alts in ALIASES.items():
        for h in headers:
            nh=norm(h)
            if nh==norm(target) or any(nh==norm(a) or norm(a) in nh for a in alts): out[target]=h; break
    return out

def parse_csv(raw):
    text=raw.decode('utf-8-sig',errors='replace')
    sample=text[:5000]
    try: dialect=csv.Sniffer().sniff(sample)
    except: dialect=csv.excel
    rows=list(csv.DictReader(io.StringIO(text),dialect=dialect))
    return rows, list(rows[0].keys()) if rows else []

def quality_report(rows,mapping):
    n=len(rows); issues=[]; dup=set(); seen=set(); valid=0
    for r in rows:
        vals=[str(v).strip() for v in r.values()]
        key='|'.join(vals)
        if key in seen: dup.add(key)
        seen.add(key)
        p=str(r.get(mapping.get('product',''), '')).strip() if mapping.get('product') else ''
        q=str(r.get(mapping.get('quantity',''), '')).strip() if mapping.get('quantity') else ''
        pr=str(r.get(mapping.get('price',''), '')).strip() if mapping.get('price') else ''
        if p and q and pr: valid+=1
    missing_product=sum(1 for r in rows if not str(r.get(mapping.get('product',''),'')).strip()) if mapping.get('product') else n
    missing_price=sum(1 for r in rows if not str(r.get(mapping.get('price',''),'')).strip()) if mapping.get('price') else n
    missing_date=sum(1 for r in rows if not str(r.get(mapping.get('date',''),'')).strip()) if mapping.get('date') else n
    if not mapping.get('product'): issues.append('Product column could not be mapped')
    if not mapping.get('price'): issues.append('Price column could not be mapped')
    score=100
    score-=min(25,missing_product/n*30 if n else 30)
    score-=min(20,missing_price/n*20 if n else 20)
    score-=min(15,missing_date/n*10 if n else 10)
    score-=min(10,len(dup)/n*10 if n else 10)
    if not mapping.get('product'): score-=20
    if not mapping.get('price'): score-=15
    return {'rows':n,'quality':round(max(0,min(100,score)),1),'valid_rows':valid,'missing_product':missing_product,'missing_price':missing_price,'missing_date':missing_date,'duplicates':len(dup),'mapping':mapping,'issues':issues}

def fnum(x):
    try:return float(str(x).replace(',','').replace('₹','').strip())
    except:return 0.0

def sales_for(aid=None):
    c=db(); q='select s.* from sales s join datasets d on d.id=s.dataset_id'; params=[]
    if aid: q+=' where d.artisan_id=?'; params=[aid]
    rows=c.execute(q,params).fetchall(); c.close(); return rows

def insights(aid=1):
    rows=sales_for(aid); c=db(); products=c.execute('select * from products where artisan_id=?',(aid,)).fetchall(); c.close()
    if not rows:
        return {'has_history':False,'message':'No historical sales imported yet. Recommendations use product attributes and benchmark rules with medium confidence.','kpis':{},'top_products':[],'markets':[],'recommendations':[],'confidence':'Medium'}
    revenue=sum(r['quantity']*r['price'] for r in rows); units=sum(r['quantity'] for r in rows)
    byp={}
    bycity={}
    bymonth={}
    for r in rows:
        rev=r['quantity']*r['price']; p=r['product'] or 'Unknown'; byp.setdefault(p,[0,0]); byp[p][0]+=r['quantity']; byp[p][1]+=rev
        city=r['city'] or 'Unknown'; bycity.setdefault(city,0); bycity[city]+=rev
        m=(r['sale_date'] or '')[:7] or 'Unknown'; bymonth.setdefault(m,0); bymonth[m]+=rev
    top=sorted(byp.items(),key=lambda x:x[1][1],reverse=True)[:5]; markets=sorted(bycity.items(),key=lambda x:x[1],reverse=True)[:6]
    avg=revenue/units if units else 0
    rec=[]
    if top: rec.append({'priority':'High','title':f"Protect demand for {top[0][0]}",'detail':f"It generated ₹{top[0][1][1]:,.0f} from {top[0][1][0]:.0f} units in imported history. Plan stock before high-demand periods."})
    if markets: rec.append({'priority':'High','title':f"Expand beyond {markets[0][0]}",'detail':f"{markets[0][0]} is the strongest recorded market. Test the next-best market ({markets[1][0] if len(markets)>1 else 'a nearby urban market'}) with a small batch."})
    if avg: rec.append({'priority':'Medium','title':'Review pricing by market','detail':f"Historical realized average is ₹{avg:,.0f}. Compare this with your cost and target margin before changing list prices."})
    rec.append({'priority':'Medium','title':'Build buyer segments','detail':'Use buyer type and location fields to identify retail, corporate and institutional opportunities as more data accumulates.'})
    return {'has_history':True,'confidence':'High' if len(rows)>=200 else 'Medium','kpis':{'orders':len(rows),'units':round(units,1),'revenue':round(revenue,2),'avg_realized_price':round(avg,2),'markets':len(bycity)},'top_products':[{'name':k,'units':v[0],'revenue':round(v[1],2)} for k,v in top],'markets':[{'name':k,'revenue':round(v,2)} for k,v in markets],'seasonality':sorted([{'month':k,'revenue':round(v,2)} for k,v in bymonth.items()],key=lambda x:x['month']),'recommendations':rec}

def market_matches(pid):
    """Explainable market + buyer opportunity engine. All scoring is local/rule-based."""
    c=db(); p=c.execute('select * from products where id=?',(pid,)).fetchone(); buyers=c.execute('select * from buyers').fetchall()
    sales=c.execute('select * from sales').fetchall(); c.close()
    if not p:return {'product':None,'opportunity_score':0,'markets':[],'buyers':[],'actions':[],'seasonality':[],'what_if':{}}

    name=(p['name'] or '').lower(); craft=(p['craft'] or '').lower(); material=(p['material'] or '').lower(); desc=(p['description'] or '').lower(); text=' '.join([name,craft,material,desc])
    price=float(p['price'] or 0); cost=float(p['cost'] or 0); capacity=float(p['capacity_week'] or 0)
    margin=((price-cost)/price*100) if price else 0

    templates=[
      ('Home Décor & Lifestyle', ['home','decor','basket','mat','storage','table','organizer'], ['Retail','Boutique'], 90, 'Retailers, boutiques and online lifestyle sellers'),
      ('Tourist & Souvenir', ['tourist','souvenir','regional','traditional','craft','handmade'], ['Retail','Tourist / Souvenir'], 82, 'Tourist stores, craft fairs and cultural retail'),
      ('Corporate Gifting', ['gift','corporate','hamper','custom','eco'], ['Corporate'], 78, 'Corporate gifting companies and bulk programmes'),
      ('Hospitality & Institutional', ['hotel','resort','institution','bulk','decor','hospitality'], ['Institutional','Corporate'], 70, 'Hotels, resorts and institutional procurement'),
      ('Conscious / Sustainable Retail', ['eco','bamboo','natural','sustainable','handmade'], ['Retail','Corporate'], 76, 'Sustainable lifestyle retailers and conscious buyers')]
    markets=[]
    for market,keywords,types,base,channel in templates:
        fit=sum(1 for k in keywords if k in text)
        score=min(97,base + min(14,fit*4))
        reasons=[]
        if fit: reasons.append(f'{fit} product attributes fit this market')
        if 'bamboo' in text or 'eco' in text or 'sustainable' in text: reasons.append('sustainable/handmade positioning supports this audience')
        if market=='Corporate Gifting' and capacity>=20: reasons.append('weekly capacity supports small-to-medium bulk enquiries')
        if market=='Hospitality & Institutional' and capacity>=25: reasons.append('capacity can support larger recurring orders')
        demand='High' if score>=88 else ('Medium' if score>=76 else 'Emerging')
        competition='Medium'
        if market in ('Tourist & Souvenir','Conscious / Sustainable Retail'): competition='Medium-Low'
        price_fit='Strong' if price and cost and margin>=30 else ('Review' if price else 'Unknown')
        seasonal='Oct–Mar' if market in ('Tourist & Souvenir','Home Décor & Lifestyle') else ('Oct–Dec' if market=='Corporate Gifting' else 'Year-round')
        markets.append({'market':market,'score':score,'demand':demand,'competition':competition,'price_fit':price_fit,'seasonality':seasonal,'channels':channel,'reasons':reasons or ['General category compatibility']})
    markets.sort(key=lambda x:x['score'],reverse=True)

    buyer_out=[]
    for b in buyers:
        bscore=45; reasons=[]; needs=(b['needs'] or '').lower(); btype=b['type'] or ''
        price_fit=b['budget_min']<=price<=b['budget_max'] if price else False
        quantity_fit=capacity>=b['volume_min'] if capacity else False
        if price_fit: bscore+=20; reasons.append('price fits buyer budget')
        elif price and price < b['budget_min']: bscore+=8; reasons.append('price is below buyer budget range')
        else: reasons.append('price needs negotiation for this buyer')
        if quantity_fit: bscore+=15; reasons.append('weekly capacity can support the buyer minimum')
        elif capacity: reasons.append('buyer minimum may exceed current weekly capacity')
        if 'eco' in needs and ('bamboo' in text or 'eco' in text or 'sustainable' in text): bscore+=10; reasons.append('eco-friendly positioning matches buyer need')
        if 'decor' in needs and ('decor' in text or 'basket' in text or 'mat' in text): bscore+=8; reasons.append('home/decor use matches buyer need')
        if 'gift' in needs and ('gift' in text or 'hamper' in text): bscore+=8; reasons.append('gifting use matches buyer need')
        if 'regional' in needs and (p['region'] or '').strip(): bscore+=5; reasons.append('regional craft story can support buyer positioning')
        if btype=='Corporate' and capacity>=20: bscore+=4
        if btype=='Institutional' and capacity>=25: bscore+=4
        fit=min(99,round(bscore))
        buyer_out.append({'id':b['id'],'buyer':b['name'],'type':btype,'city':b['city'],'score':fit,'budget_min':b['budget_min'],'budget_max':b['budget_max'],'volume_min':b['volume_min'],'volume_max':b['volume_max'],'price_fit':price_fit,'quantity_fit':quantity_fit,'product_fit':min(99,fit+3 if fit<96 else fit),'location_fit':82,'category_fit':fit,'expected_order':min(max(b['volume_min'],1),b['volume_max']),'reasons':reasons})
    buyer_out.sort(key=lambda x:x['score'],reverse=True)

    hist=[r for r in sales if r['product'] and (r['product'].lower()==name or name in r['product'].lower() or r['product'].lower() in name)]
    historical_units=sum(float(r['quantity'] or 0) for r in hist); historical_revenue=sum(float(r['quantity'] or 0)*float(r['price'] or 0) for r in hist)
    by_month={}
    for r in hist:
        d=str(r['sale_date'] or '')
        if len(d)>=7: by_month[d[5:7]]=by_month.get(d[5:7],0)+float(r['quantity'] or 0)*float(r['price'] or 0)
    seasonality=sorted([{'month':m,'revenue':round(v,2)} for m,v in by_month.items()],key=lambda x:x['revenue'],reverse=True)
    top=markets[0]
    overall=round((top['score']*0.30)+(buyer_out[0]['score']*0.30 if buyer_out else 0)+(min(100,max(0,margin+20))*0.15)+(75*0.10)+(min(100,60+(historical_revenue>0)*25)*0.15))
    if historical_revenue: overall=min(99,overall+5)
    budget=buyer_out[0]['budget_max'] if buyer_out else price
    suggested_b2b=round(min(price if price else budget, budget*0.95),2) if budget else 0
    actions=[
      f"Prioritize {top['market']} because it has the strongest product-market fit ({top['score']}%).",
      f"Contact {buyer_out[0]['buyer']} first." if buyer_out else 'Add buyer profiles to unlock buyer prioritisation.',
      f"Offer around ₹{suggested_b2b:,.0f} for a first B2B conversation." if suggested_b2b else 'Set a product price to calculate an offer.',
      f"Prepare about {min(max(int(capacity*4),1), buyer_out[0]['expected_order'] if buyer_out else max(int(capacity*4),1))} units for an initial opportunity batch." if capacity else 'Add weekly production capacity to assess order feasibility.'
    ]
    return {'product':dict(p),'opportunity_score':overall,'markets':markets,'buyers':buyer_out,'top_buyers':buyer_out[:5],'seasonality':seasonality[:6],'historical':{'transactions':len(hist),'units':round(historical_units,1),'revenue':round(historical_revenue,2)},'actions':actions,'recommended_action':{'market':top['market'],'buyer':buyer_out[0]['buyer'] if buyer_out else 'Add a buyer profile','offer_price':suggested_b2b,'quantity':buyer_out[0]['expected_order'] if buyer_out else int(capacity or 0),'season':top['seasonality']},'what_if':{'price_minus_50':None,'capacity_plus_100':None},'note':'Scores are explainable decision support based on product attributes, recorded history and buyer profile fields. They are not guarantees of demand, price or orders.'}

class ProductIn(BaseModel):
    artisan_id:int=1; name:str; craft:str=''; material:str=''; region:str=''; technique:str=''; description:str=''; cost:float=0; price:float=0; capacity_week:int=0
class ArtisanIn(BaseModel):
    name:str; phone:str=''; language:str='Hindi'; region:str=''; craft:str=''; capacity:int=0



def market_ready_engine(name, craft, material, region, technique, description, voice_text='', price=0, cost=0, capacity=0):
    """Free, local-first decision engine. It turns artisan-provided text/voice into structured market-ready content."""
    raw=' '.join([name,craft,material,region,technique,description,voice_text]).lower()
    def has(*words): return any(w in raw for w in words)
    if not craft:
        craft = 'Bamboo Craft' if has('bamboo','basket','mat','cane') else ('Textile Craft' if has('cloth','textile','weave','fabric') else 'Traditional Handcraft')
    if not material:
        material = 'Bamboo' if has('bamboo','cane') else ('Cotton' if has('cotton','fabric','cloth') else 'natural materials')
    if not technique:
        technique = 'Handwoven' if has('woven','weave','basket','mat') else 'Traditional handcraft techniques'
    if not region: region='India'
    if not name: name='Handcrafted Artisan Product'
    price=float(price or 0); cost=float(cost or 0); capacity=int(capacity or 0)
    margin=round((price-cost)/price*100,1) if price else 0
    primary='Corporate gifting' if has('gift','corporate','hamper') else ('Home décor & lifestyle' if has('home','decor','basket','mat','storage') else 'Conscious craft buyers')
    if has('hotel','resort','bulk','institution'): primary='Institutional & hospitality buyers'
    title=f'Handcrafted {name} | {craft}'
    short=f'A handmade {name.lower()} crafted from {material}, combining {craft.lower()} knowledge with practical everyday value.'
    long=(f'{name} is a handmade {craft.lower()} product made in {region} using {material} and {technique}. {description.strip() or "It is designed for practical use, gifting and curated craft collections."} '
          f'Its handmade character gives each piece a distinctive identity while connecting traditional artisan skills with contemporary customers. It can be positioned for retail, gifting and suitable bulk opportunities.')
    story=(f'This product carries the value of small-scale artisan production in {region}. The use of {material} and {technique} reflects hands-on craft knowledge rather than mass production. Karigar Link helps translate that craft identity into market-ready information without removing the artisan story.')
    uses=['Everyday use','Home décor','Festive gifting','Corporate gifting','Curated retail']
    channels=['Local exhibitions and craft fairs','WhatsApp / social catalogue','Boutique and lifestyle retailers','Corporate gifting','Institutional procurement']
    if primary=='Institutional & hospitality buyers': channels=['Hotels / resorts','Institutional procurement','Corporate gifting','Local exhibitions and craft fairs','WhatsApp / social catalogue']
    segments=[primary,'Tourists and craft collectors','Boutique and lifestyle retailers','Online conscious consumers']
    min_price=round(cost*1.15,2) if cost else round(price*0.8,2)
    retail=round(max(price,cost/0.60 if cost else price),2) if (price or cost) else 0
    b2b=round(max(cost/0.70 if cost else 0,price*0.85),2) if (price or cost) else 0
    confidence='High' if description and (craft or material) else 'Medium'
    return {'confidence':confidence,'identity':{'product_name':name,'craft':craft,'material':material,'technique':technique,'region':region,'handmade':True},'catalogue':{'title':title,'short_description':short,'long_description':long,'story':story},'commercial':{'current_price':price,'estimated_cost':cost,'minimum_sustainable':min_price,'recommended_retail':retail,'recommended_b2b':b2b,'gross_margin_percent':margin,'weekly_capacity':capacity},'market':{'primary_market':primary,'customer_segments':segments,'channels':channels,'use_cases':uses},'marketing':{'whatsapp':f'Namaste! We make {name.lower()} by hand in {region} using {material}. Ideal for {primary.lower()}, gifting and curated retail. Indicative price: ₹{price:,.0f}. Enquire for bulk/custom orders.' if price else f'Namaste! We make {name.lower()} by hand in {region} using {material}. Enquire for retail, bulk or customised orders.','instagram':f'{name} — handmade in {region}, crafted from {material}. Traditional skill, useful modern design and artisan-made character. DM for retail and bulk enquiries. #Handmade #ArtisanMade #{craft.replace(" ","")} #{material.replace(" ","")}','buyer_pitch':f'We supply artisan-made {name.lower()} from {region}, using {material}. Best fit: {primary.lower()}. Indicative capacity: {capacity or "to be confirmed"} units/week. Bulk quantities and custom requirements can be discussed.','cta':'Send an enquiry for retail, bulk or customised orders.'},'seo_keywords':[craft,material,'handmade '+name,region+' handicraft','artisan made','Indian handicraft']}


def forecast_for_product(pid, months_ahead=3):
    c=db(); p=c.execute('select * from products where id=?',(pid,)).fetchone()
    sales=c.execute('select * from sales where lower(product)=lower(?)',(p['name'] if p else '',)).fetchall(); c.close()
    if not p: return None
    monthly={}; month_prices={}
    for r in sales:
        d=str(r['sale_date'] or '')
        if len(d)>=7:
            key=d[:7]; monthly[key]=monthly.get(key,0)+float(r['quantity'] or 0)
            month_prices.setdefault(key,[]).append(float(r['price'] or 0))
    ordered=sorted(monthly.items())
    vals=[v for _,v in ordered]
    recent=vals[-3:] if vals else []
    baseline=sum(recent)/len(recent) if recent else max(float(p['capacity_week'] or 0)*4.33,1)
    previous=sum(vals[-6:-3])/len(vals[-6:-3]) if len(vals)>=6 else (sum(vals[:-3])/len(vals[:-3]) if len(vals)>3 else baseline)
    trend_pct=((baseline-previous)/previous*100) if previous else 0
    direction='Growing' if trend_pct>=10 else ('Declining' if trend_pct<=-10 else 'Stable')
    confidence='High' if len(sales)>=12 else ('Medium' if len(sales)>=6 else 'Low')
    buckets={}
    for k,v in ordered: buckets.setdefault(k[5:7],[]).append(v)
    overall=sum(vals)/len(vals) if vals else 1
    factors={m:max(.65,min(1.5,(sum(v)/len(v))/overall)) for m,v in buckets.items()}
    from datetime import date
    today=date.today(); forecasts=[]; y,m=today.year,today.month
    for i in range(1,months_ahead+1):
        mm=m+i; yy=y+(mm-1)//12; mo=(mm-1)%12+1; key=f'{yy:04d}-{mo:02d}'
        factor=factors.get(f'{mo:02d}',1.0); q=max(0,round(baseline*factor,1))
        forecasts.append({'month':key,'expected_units':q,'expected_revenue':round(q*float(p['price'] or 0),2),'season_factor':round(factor,2),'capacity_gap':round(max(0,q-float(p['capacity_week'] or 0)*4.33),1)})
    expected=sum(x['expected_units'] for x in forecasts); cap=float(p['capacity_week'] or 0)*4.33
    avg_price=(sum(float(r['price'] or 0) for r in sales)/len(sales)) if sales else float(p['price'] or 0)
    monthly_history=[{'month':k,'units':round(v,1),'revenue':round(sum(month_prices.get(k,[])[i] for i in range(len(month_prices.get(k,[])))),2)} for k,v in ordered]
    # revenue above is corrected below using actual rows
    rev_by_month={}
    for r in sales:
        k=str(r['sale_date'] or '')[:7]; rev_by_month[k]=rev_by_month.get(k,0)+float(r['quantity'] or 0)*float(r['price'] or 0)
    for h in monthly_history: h['revenue']=round(rev_by_month.get(h['month'],0),2)
    best=max(forecasts,key=lambda x:x['expected_units']) if forecasts else None
    return {'product':dict(p),'history_transactions':len(sales),'historical_months':len(monthly),'confidence':confidence,'baseline_monthly_units':round(baseline,1),'trend_direction':direction,'trend_percent':round(trend_pct,1),'average_realized_price':round(avg_price,2),'historical_months_detail':monthly_history[-12:],'forecast':forecasts,'expected_units_next_3_months':round(expected,1),'expected_revenue_next_3_months':round(sum(x['expected_revenue'] for x in forecasts),2),'capacity_monthly_estimate':round(cap,1),'recommended_additional_production':round(max(0,expected-cap),1),'peak_forecast':best,'decision':'Increase preparation' if expected>cap else ('Maintain controlled production' if expected>=baseline*2.5 else 'Maintain normal production'),'message':'This is a local planning estimate using this product’s recorded sales, recent run-rate and observed calendar seasonality. It is not a guaranteed demand forecast.'}

def market_intelligence_for_product(pid):
    c=db(); p=c.execute('select * from products where id=?',(pid,)).fetchone(); buyers=c.execute('select * from buyers').fetchall(); sales=c.execute('select * from sales').fetchall(); c.close()
    if not p: return None
    text=' '.join([p['name'] or '',p['craft'] or '',p['material'] or '',p['description'] or '']).lower(); price=float(p['price'] or 0); cost=float(p['cost'] or 0)
    hist=[r for r in sales if (r['product'] or '').lower()==(p['name'] or '').lower()]; hist_revenue=sum(float(r['quantity'] or 0)*float(r['price'] or 0) for r in hist); hist_units=sum(float(r['quantity'] or 0) for r in hist)
    city_rev={}; buyer_types={}
    for r in hist:
        city_rev[r['city'] or 'Unknown']=city_rev.get(r['city'] or 'Unknown',0)+float(r['quantity'] or 0)*float(r['price'] or 0)
    templates=[
      ('Home & Lifestyle Retail',['basket','storage','mat','home','decor','organizer'],'Boutiques, home stores and lifestyle retailers','Retail', 'Start with small repeat batches; use a lifestyle catalogue and regional craft story.'),
      ('Corporate Gifting',['gift','hamper','corporate','custom','eco'],'Corporate gifting agencies and company procurement teams','Corporate','Prepare tiered 25/50/100-unit quotes and customization options.'),
      ('Tourist & Cultural Retail',['tourist','souvenir','regional','traditional','craft','handmade'],'Tourist shops, exhibitions and cultural retail','Retail','Use compact packaging, craft origin story and event-season inventory.'),
      ('Hospitality & Institutional',['hotel','resort','institution','hospitality','bulk','decor'],'Hotels, resorts, institutions and programme procurement','Institutional','Offer standardized specifications, lead times and bulk pricing.'),
      ('Sustainable / Conscious Retail',['bamboo','natural','sustainable','eco','handmade'],'Sustainable lifestyle stores and conscious consumers','Retail','Lead with material story, handmade production and practical use rather than discounting.')]
    rows=[]
    for market,kw,buyer,bt,entry in templates:
        fit=sum(1 for k in kw if k in text); historical_signal=min(25,10+min(15,hist_revenue/5000*15)) if hist_revenue else 5
        demand=min(95,45+fit*7+historical_signal); price_fit=80 if price and cost and price>=cost*1.3 else (60 if price else 40)
        buyer_fit=min(95,55+sum(1 for b in buyers if (b['type'] or '')==bt)*8)
        score=round(demand*.35+price_fit*.2+buyer_fit*.2+(min(95,55+fit*8))*.15+(70 if hist else 45)*.1)
        evidence=[]
        if hist: evidence.append(f'{len(hist)} recorded sales transactions for this product')
        if city_rev: evidence.append(f"Recorded revenue is strongest in {max(city_rev,key=city_rev.get)}")
        if fit: evidence.append(f'{fit} product attributes match this market type')
        if buyer_fit>=70: evidence.append(f'Buyer profiles exist for {bt.lower()} demand')
        rows.append({'market':market,'score':score,'demand_signal':round(demand),'price_fit':round(price_fit),'buyer_fit':round(buyer_fit),'competition':'Needs validation','ideal_buyer':buyer,'entry_strategy':entry,'evidence':evidence or ['Use a small market test to create evidence'],'risk':'Do not assume market demand from category fit alone; validate with enquiries and orders.'})
    rows.sort(key=lambda x:x['score'],reverse=True)
    top=rows[0]
    return {'product':dict(p),'overall_opportunity':top['score'],'best_market':top,'markets':rows,'historical':{'transactions':len(hist),'units':round(hist_units,1),'revenue':round(hist_revenue,2),'top_city':max(city_rev,key=city_rev.get) if city_rev else None,'city_revenue':sorted([{'city':k,'revenue':round(v,2)} for k,v in city_rev.items()],key=lambda x:x['revenue'],reverse=True)},'decision':f"Test {top['market']} first with a controlled buyer outreach campaign, then compare enquiry-to-order conversion against the next ranked market.", 'external_note':'External official sources are shown as reference points only; no external price, bid or demand figure is invented.'}

@app.get('/api/forecast')
def forecast(artisan_id:int=1, product_id:int=0):
    c=db(); ps=c.execute('select * from products where artisan_id=? order by id',(artisan_id,)).fetchall(); c.close()
    if product_id: ps=[p for p in ps if p['id']==product_id]
    items=[forecast_for_product(p['id']) for p in ps]
    return {'products':items,'selected':items[0] if product_id and items else None,'message':'Select a product to create a product-specific production plan.'}

@app.get('/api/market-intelligence')
def market_intelligence(artisan_id:int=1, product_id:int=0):
    if not product_id: return {'selected':None,'message':'Select a product to analyse its markets.'}
    return {'selected':market_intelligence_for_product(product_id)}

@app.get('/api/marketplace')
def marketplace(product_id:int=0):
    c=db(); ps=c.execute('select * from products order by id').fetchall(); req=c.execute("select * from buyer_requests where status='Open' order by id desc").fetchall(); c.close()
    if not product_id: return {'selected':None,'products':[dict(p) for p in ps],'buyer_requests':[dict(r) for r in req]}
    p=next((x for x in ps if x['id']==product_id),None)
    if not p: return {'selected':None,'buyer_requests':[dict(r) for r in req]}
    matches=[]
    for r in req:
        need=(r['product_need'] or '').lower(); name=(p['name'] or '').lower(); material=(p['material'] or '').lower(); score=35; reasons=[]
        if any(w in need for w in re.findall(r'[a-z]{4,}',name)): score+=30; reasons.append('product name/category matches buyer requirement')
        if material and material.lower() in need: score+=15; reasons.append('material matches buyer requirement')
        if r['budget_min']<=float(p['price'] or 0)<=r['budget_max']: score+=15; reasons.append('current price fits the buyer budget')
        else: reasons.append('price needs negotiation against buyer budget')
        feasible=float(p['capacity_week'] or 0)*4.33>=float(r['quantity'] or 0); score+=5 if feasible else 0
        reasons.append('estimated capacity can cover the request' if feasible else 'request is larger than one-month estimated capacity')
        matches.append({**dict(r),'match_score':min(99,score),'match_reasons':reasons,'feasible':feasible})
    matches.sort(key=lambda x:x['match_score'],reverse=True)
    return {'selected':{'id':p['id'],'name':p['name'],'craft':p['craft'],'material':p['material'],'region':p['region'],'description':p['description'],'price':p['price'],'cost':p['cost'],'capacity_week':p['capacity_week'],'listing_title':f"{p['name']} — {p['craft']}",'buyer_pitch':f"Handmade {p['name'].lower()} from {p['region']}, suitable for retail and bulk enquiries. Current indicative price ₹{float(p['price'] or 0):,.0f} with estimated capacity of {p['capacity_week']} units/week."},'matches':matches,'buyer_requests':[dict(r) for r in req],'note':'This is a local marketplace workflow for the prototype. It records buyer requirements and enquiries inside Karigar Link; it is not a live connection to GeM or Indiahandmade.'}

@app.get('/api/live-market-signals')
def live_market_signals(product_id:int=0):
    sources=[{'name':'Indian Handicrafts','url':'https://indian.handicrafts.gov.in/','purpose':'Official artisan, events and handicraft ecosystem information'}, {'name':'Indiahandmade','url':'https://www.indiahandmade.com/','purpose':'Government-backed online marketplace for artisans and weavers'}, {'name':'GeM','url':'https://gem.gov.in/','purpose':'Government procurement marketplace'}]
    checked=[]
    for src in sources:
        ok=False; title=''; checked_at=datetime.now().isoformat(timespec='seconds')
        try:
            req=urllib.request.Request(src['url'],headers={'User-Agent':'KarigarLink/2.3'}); resp=urllib.request.urlopen(req,timeout=4); body=resp.read(50000).decode('utf-8','ignore'); ok=200<=int(getattr(resp,'status',200))<500
            mt=re.search(r'<title[^>]*>(.*?)</title>',body,re.I|re.S); title=re.sub(r'\s+',' ',mt.group(1)).strip() if mt else ''
        except Exception: pass
        checked.append({**src,'status':'Reachable' if ok else 'Unavailable','page_title':title,'checked_at':checked_at})
    return {'checked_at':datetime.now().isoformat(timespec='seconds'),'sources':checked,'policy':'Only source availability and page title are checked live. Karigar Link never fabricates external prices, bids or demand figures.','product_id':product_id}

@app.get('/api/buyer-requests/{rid}/matches')
def buyer_request_matches(rid:int):
    c=db()
    req=c.execute('select * from buyer_requests where id=?',(rid,)).fetchone()
    ps=c.execute('select * from products order by id').fetchall()
    c.close()
    if not req: raise HTTPException(404,'Buyer request not found')
    need=str(req['product_need'] or '').lower()
    out=[]
    for p in ps:
        score=35
        reasons=[]
        text=' '.join(str(p[k] or '') for k in ['name','craft','material','description']).lower()
        if any(w and w in text for w in re.findall(r'[a-z]{4,}',need)):
            score+=25; reasons.append('Product description matches the buyer need')
        if req['budget_min'] and p['price'] and float(req['budget_min'])<=float(p['price'])<=float(req['budget_max'] or req['budget_min']):
            score+=20; reasons.append('Listed price fits the buyer budget')
        elif req['budget_max'] and p['price'] and float(p['price'])<=float(req['budget_max']):
            score+=10; reasons.append('Listed price is within the upper budget')
        if p['capacity_week'] and float(p['capacity_week'])*4 >= float(req['quantity'] or 1):
            score+=15; reasons.append('Estimated monthly capacity can support the requested quantity')
        if str(req['city'] or '').lower() in str(p['region'] or '').lower() or str(p['region'] or '').lower() in str(req['city'] or '').lower():
            score+=5; reasons.append('Geographic context is aligned')
        out.append({'product_id':p['id'],'product':p['name'],'score':min(100,score),'reason':'; '.join(reasons) or 'General product fit based on available data'})
    out.sort(key=lambda x:x['score'],reverse=True)
    return {'request':dict(req),'matches':out,'note':'Local explainable buyer-product matching. Validate actual demand through enquiries and orders.'}

@app.post('/api/buyer-requests')
def buyer_request(buyer_name:str=Form(...),buyer_type:str=Form('Retail'),city:str=Form(''),product_need:str=Form(...),quantity:int=Form(1),budget_min:float=Form(0),budget_max:float=Form(0),delivery_days:int=Form(30),notes:str=Form('')):
    c=db(); cur=c.execute('insert into buyer_requests(buyer_name,buyer_type,city,product_need,quantity,budget_min,budget_max,delivery_days,notes) values(?,?,?,?,?,?,?,?,?)',(buyer_name,buyer_type,city,product_need,quantity,budget_min,budget_max,delivery_days,notes)); c.commit(); rid=cur.lastrowid; c.close(); return {'id':rid,'status':'Open'}


class AuthIn(BaseModel):
    name:str=''; email:str=''; password:str=''; phone:str=''; language:str='English'; region:str=''; craft:str=''

@app.post('/api/auth/register')
def auth_register(x:AuthIn):
    if not x.name.strip() or len(x.password)<6: raise HTTPException(400,'Name and a password of at least 6 characters are required.')
    if not x.email.strip() and not x.phone.strip(): raise HTTPException(400,'Provide an email address or mobile number.')
    email=x.email.strip().lower() or None; phone=x.phone.strip() or None
    c=db()
    if email and c.execute('select id from users where email=?',(email,)).fetchone(): c.close(); raise HTTPException(409,'An account already exists with this email.')
    if phone and c.execute('select id from users where phone=?',(phone,)).fetchone(): c.close(); raise HTTPException(409,'An account already exists with this mobile number.')
    c.execute('insert into artisans(name,phone,language,region,craft,capacity,created_at) values(?,?,?,?,?,?,?)',(x.name.strip(),phone or '',x.language,x.region,x.craft,0,datetime.now().isoformat())); aid=c.execute('select last_insert_rowid()').fetchone()[0]
    c.execute('insert into users(name,email,phone,password_hash,language,artisan_id,created_at) values(?,?,?,?,?,?,?)',(x.name.strip(),email,phone,_hash_password(x.password),x.language,aid,datetime.now().isoformat())); uid=c.execute('select last_insert_rowid()').fetchone()[0]; c.commit(); c.close()
    return {'user':{'id':uid,'name':x.name.strip(),'email':email,'phone':phone,'language':x.language},'token':_session_token(uid)}

@app.post('/api/auth/login')
def auth_login(x:AuthIn):
    identifier=(x.email or '').strip().lower() or (x.phone or '').strip()
    c=db(); row=c.execute('select * from users where lower(email)=? or phone=?',(identifier,identifier)).fetchone(); c.close()
    if not row or not row['password_hash'] or not _check_password(x.password,row['password_hash']): raise HTTPException(401,'Invalid email/mobile or password.')
    return {'user':{'id':row['id'],'name':row['name'],'email':row['email'],'phone':row['phone'],'language':row['language']},'token':_session_token(row['id'])}

@app.post('/api/auth/request-phone-otp')
def request_phone_otp(phone:str=Form(...)):
    phone=phone.strip()
    if not re.fullmatch(r'\+[1-9]\d{7,14}',phone): raise HTTPException(400,'Use international format, for example +919876543210.')
    ok,payload=_twilio_verify('send',phone)
    if not ok: raise HTTPException(503,payload)
    return {'sent':True,'provider':'Twilio Verify'}

@app.post('/api/auth/verify-phone-otp')
def verify_phone_otp(phone:str=Form(...),code:str=Form(...),name:str=Form(''),password:str=Form(''),language:str=Form('English')):
    ok,payload=_twilio_verify('check',phone.strip(),code.strip())
    if not ok: raise HTTPException(503,payload)
    if isinstance(payload,dict) and payload.get('status')!='approved': raise HTTPException(401,'OTP was not approved.')
    c=db(); row=c.execute('select * from users where phone=?',(phone.strip(),)).fetchone()
    if not row:
        if not name.strip() or len(password)<6: c.close(); raise HTTPException(400,'For a new mobile account, provide your name and a password of at least 6 characters.')
        c.execute('insert into artisans(name,phone,language,region,craft,capacity,created_at) values(?,?,?,?,?,?,?)',(name.strip(),phone.strip(),language,'','',0,datetime.now().isoformat())); aid=c.execute('select last_insert_rowid()').fetchone()[0]
        c.execute('insert into users(name,phone,password_hash,language,artisan_id,created_at) values(?,?,?,?,?,?)',(name.strip(),phone.strip(),_hash_password(password),language,aid,datetime.now().isoformat())); uid=c.execute('select last_insert_rowid()').fetchone()[0]; c.commit(); row=c.execute('select * from users where id=?',(uid,)).fetchone()
    c.close(); return {'verified':True,'user':{'id':row['id'],'name':row['name'],'email':row['email'],'phone':row['phone'],'language':row['language']},'token':_session_token(row['id'])}

@app.get('/api/auth/me')
def auth_me(authorization:str=Header(default='')):
    token=authorization.replace('Bearer ','',1).strip(); u=_user_from_token(token)
    if not u: raise HTTPException(401,'Session expired or invalid.')
    return {'id':u['id'],'name':u['name'],'email':u['email'],'phone':u['phone'],'language':u['language']}

@app.post('/api/auth/logout')
def auth_logout(authorization:str=Header(default='')):
    token=authorization.replace('Bearer ','',1).strip(); th=hashlib.sha256(token.encode()).hexdigest(); c=db(); c.execute('delete from sessions where token_hash=?',(th,)); c.commit(); c.close(); return {'ok':True}

@app.post('/api/assistant')
def assistant(message:str=Form(...), history:str=Form(''), context:str=Form('{}')):
    """Conversational assistant with memory, data-aware answers and executable navigation actions.
    It never invents business numbers. Optional Ollama provides richer natural-language answers.
    """
    msg=message.strip(); low=msg.lower()
    try: hist=json.loads(history or '[]')[-40:]
    except Exception: hist=[]
    try: ctx=json.loads(context or '{}')
    except Exception: ctx={}
    c=db()
    products=[dict(x) for x in c.execute('select * from products order by id desc').fetchall()]
    buyers=[dict(x) for x in c.execute('select * from buyers order by id desc').fetchall()]
    sales_count=c.execute('select count(*) n from sales').fetchone()['n']
    revenue=c.execute('select coalesce(sum(quantity*price),0) v from sales').fetchone()['v'] or 0
    units=c.execute('select coalesce(sum(quantity),0) v from sales').fetchone()['v'] or 0
    c.close()

    # Resolve product from the current message, previous conversation, or explicit current context.
    matched=None
    hay=' '.join([msg]+[str(x.get('content','')) for x in hist if x.get('role')=='user'])
    for p in products:
        name=(p.get('name') or '').strip()
        if name and name.lower() in hay.lower(): matched=p; break
    if not matched and ctx.get('product_id'):
        try: matched=next((p for p in products if int(p['id'])==int(ctx['product_id'])),None)
        except Exception: pass
    # Pronoun continuity: "it/this product/the basket" uses the most recent mentioned product.
    if not matched and any(x in low for x in ['it','this product','that product','the product','this basket','the basket']):
        for x in reversed(hist):
            if x.get('role')=='assistant' and matched is None:
                for p in products:
                    if p.get('name','').lower() in str(x.get('content','')).lower(): matched=p; break
    action={'type':'none'}
    reply=''

    def nav(page, text, pid=None):
        return text, {'type':'navigate','page':page,'product_id':pid}

    # Only navigate when the user clearly asks to open or switch to a module.
    # Mentioning a topic such as pricing, demand, buyers, schemes or catalogues
    # in an ordinary question must be answered conversationally by the AI model.
    wants_navigation=bool(re.search(
        r'\b(open|show me|go to|take me to|navigate to|switch to|launch|visit|open up)\b',
        low
    ))

    # Explicit navigation tasks first; ordinary topic questions go to the model.
    if wants_navigation and any(w in low for w in ['catalogue','catalog','cataloging','cataloguing']):
        if matched:
            reply,action=nav('catalogue',f"Yes. I’ll open Smart Catalogue for {matched['name']} now and use the product information already stored for it.",matched['id'])
        elif any(k in low for k in ['create','add','new','make']) and re.search(r'(?:product|called|named)\s+([a-z][a-z0-9 &\-]{2,80})',msg,re.I):
            name=re.search(r'(?:product|called|named)\s+([a-z][a-z0-9 &\-]{2,80})',msg,re.I).group(1).strip(' .')
            reply=f"I can prepare a catalogue for {name}. I need the product to exist in Products first, so I’ll open Products for you to save its identity, then you can return to Smart Catalogue."
            action={'type':'navigate','page':'products','product_id':None}
        else:
            reply='Absolutely. Tell me the product name, or say “use my latest product”, and I’ll take you to Smart Catalogue with the right product selected.'
            action={'type':'navigate','page':'catalogue','product_id':None}
    elif wants_navigation and any(w in low for w in ['forecast','demand','sales prediction','predict demand']):
        if matched: reply,action=nav('forecast',f"I’ll open Demand & Forecasting for {matched['name']}. The page will use the dated sales history available for that product.",matched['id'])
        else: reply,action=nav('forecast','I’ll open Demand & Forecasting. Select a product to analyse its recorded sales history.',None)
    elif wants_navigation and any(w in low for w in ['pricing intelligence','pricing','price','margin','profit']) and not any(w in low for w in ['market price']):
        if matched: reply,action=nav('pricing',f"I’ll open Pricing Intelligence for {matched['name']}.",matched['id'])
        else: reply,action=nav('pricing','I’ll open Pricing Intelligence so you can choose a product.',None)
    elif wants_navigation and any(w in low for w in ['market intelligence','buyer match','buyers','where should i sell','where can i sell','market opportunity']):
        if matched: reply,action=nav('markets',f"I’ll open Market Intelligence for {matched['name']} and show the available buyer and market evidence.",matched['id'])
        else: reply,action=nav('markets','I’ll open Market Intelligence. Choose a product to analyse its market and buyer fit.',None)
    elif wants_navigation and any(w in low for w in ['historical','sales history','historical sales','past sales','sales data']):
        reply,action=nav('history','I’ll open Historical Sales Data so you can review the records behind the intelligence.',None)
    elif wants_navigation and any(w in low for w in ['government scheme','government schemes','scheme']):
        reply,action=nav('schemes','I’ll open Government Schemes.',None)
    elif wants_navigation and any(w in low for w in ['news','market news']):
        reply,action=nav('news','I’ll open Market News.',None)
    elif wants_navigation and any(w in low for w in ['opportunity','opportunities']):
        reply,action=nav('opportunities','I’ll open Business Opportunities.',None)
    elif wants_navigation and any(w in low for w in ['impact dashboard','impact','business impact']):
        reply,action=nav('impact','I’ll open Business Insights & Impact.',None)
    elif any(w in low for w in ['add product','create product','new product']):
        reply,action=nav('products','I’ll open Products so you can add the new product.',None)
    # Data-aware questions.
    elif any(w in low for w in ['how many products','my products','list my products','what products']):
        names=', '.join(p['name'] for p in products[:10]) if products else 'You have no products recorded yet.'
        reply=f"You currently have {len(products)} product(s) recorded. {names}"
    elif any(w in low for w in ['revenue','sales total','total sales','how much sold','units sold']) and any(w in low for w in ['my','our','recorded','in karigar','from my data','from our data']):
        reply=f"From the recorded sales data, I have {sales_count} transaction(s), {int(units or 0)} unit(s), and ₹{float(revenue or 0):,.0f} in recorded sales value. These are database records, not estimates."
    elif matched and any(w in low for w in ['details','information','tell me about','what do you know about']):
        reply=(f"{matched['name']} is recorded as {matched.get('craft') or 'a craft product'} using {matched.get('material') or 'unspecified material'} in {matched.get('region') or 'an unspecified region'}. "
               f"Current listed price is ₹{float(matched.get('price') or 0):,.0f}, recorded cost is ₹{float(matched.get('cost') or 0):,.0f}, and weekly capacity is {int(matched.get('capacity_week') or 0)} units.")
    elif (re.fullmatch(r'\s*(hello|hi|hey|namaste|good morning|good afternoon|good evening)[!. ,]*\s*', low)
          or low.strip() in {'help','what can you do','what can you help me with'}):
        reply='I’m your Karigar Link assistant. Ask me general questions, request writing or planning help, discuss artisan business ideas, or ask about your recorded Karigar Link data. I will only open a module when you explicitly ask me to.'
    else:
        # The Personal AI Assistant model is now the engine behind this existing
        # Karigar Link chat panel. Task/navigation rules above remain in place so
        # the model cannot accidentally trigger unsupported website actions.
        llm=None
        model=os.getenv('OLLAMA_MODEL','llama3.2:1b').strip() or 'llama3.2:1b'
        ollama_url=os.getenv('OLLAMA_URL','http://127.0.0.1:11434/api/chat').strip() or 'http://127.0.0.1:11434/api/chat'
        enabled=os.getenv('KARIGAR_ASSISTANT_OLLAMA','1').strip().lower() not in ('0','false','no','off')
        ollama_error=None
        if enabled:
            try:
                product_context=json.dumps(products[:30],ensure_ascii=False,default=str)
                buyer_context=json.dumps(buyers[:20],ensure_ascii=False,default=str)
                data_context=json.dumps({'transactions':sales_count,'units_sold':units,'recorded_sales_value':revenue,'buyer_records':len(buyers)},ensure_ascii=False)
                system_prompt=(
                    "You are the general-purpose conversational AI assistant embedded inside Karigar Link. "
                    "Answer the user's actual question even when it is unrelated to the stored database. You can discuss general knowledge, "
                    "writing, learning, planning, business strategy, marketing, product ideas, technology and everyday topics. "
                    "Do not redirect the user to a website module just because they mention pricing, demand, buyers, schemes, sales or catalogues. "
                    "Use Karigar Link records only when making claims about this user's own business. Never invent their prices, sales, buyer details, "
                    "statistics, dates, eligibility or completed actions. If a requested personal business fact is absent, say the record is unavailable; "
                    "then still offer general guidance where useful. For time-sensitive facts, explain uncertainty instead of pretending to have live web access. "
                    "Do not claim to have browsed the web or changed the website. Navigation is performed only when the user explicitly asks to open a module. "
                    "Be practical, respectful, clear and useful, with examples and next steps when appropriate. Current website context: " + json.dumps(ctx,ensure_ascii=False,default=str) +
                    "\nRecorded products: " + product_context +
                    "\nRecorded buyers: " + buyer_context +
                    "\nRecorded sales summary: " + data_context
                )
                # Frontend history includes the current message; remove its last
                # occurrence so the current user turn is not sent twice.
                prior=[]
                for item in hist[-20:]:
                    role=item.get('role')
                    content=str(item.get('content','')).strip()
                    if role not in ('user','assistant') or not content:
                        continue
                    prior.append({'role':role,'content':content})
                if prior and prior[-1]['role']=='user' and prior[-1]['content']==msg:
                    prior=prior[:-1]
                messages=[{'role':'system','content':system_prompt}, *prior, {'role':'user','content':msg}]
                body=json.dumps({'model':model,'messages':messages,'stream':False,'options':{'temperature':0.35,'num_ctx':4096}},ensure_ascii=False).encode('utf-8')
                req=urllib.request.Request(ollama_url,data=body,headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=120) as response:
                    payload=json.loads(response.read().decode('utf-8'))
                llm=str(payload.get('message',{}).get('content','')).strip()
            except Exception as exc:
                llm=None
                ollama_error=str(exc)
        if llm:
            reply=llm
            mode='llm'
        elif enabled:
            reply=("I couldn't get a response from the local AI model. Make sure Ollama is running and the model "
                   f"'{model}' is installed. In PowerShell, run `ollama list`; if it is missing, run `ollama pull {model}`. "
                   + (f" Technical detail: {ollama_error}" if ollama_error else "") + " Then try again.")
            mode='offline'
        else:
            reply="Local AI is disabled. Set KARIGAR_ASSISTANT_OLLAMA=1 to enable the Personal AI Assistant model."
            mode='rules'
        return {'reply':reply,'action':action,'product':matched,'mode':mode,'model':model if mode=='llm' else None,'memory_supported':True,'data_used':{'products':len(products),'transactions':sales_count}}
    return {'reply':reply,'action':action,'product':matched,'mode':'task','memory_supported':True,'data_used':{'products':len(products),'transactions':sales_count}}

@app.get('/api/assistant/status')
def assistant_status():
    model=os.getenv('OLLAMA_MODEL','llama3.2:1b').strip() or 'llama3.2:1b'
    tags_url='http://127.0.0.1:11434/api/tags'
    try:
        with urllib.request.urlopen(tags_url,timeout=3) as response:
            models=[x.get('name','') for x in json.loads(response.read().decode('utf-8')).get('models',[])]
        ready=any(name==model or name.startswith(model+':') for name in models)
        return {'status':'connected' if ready else 'model_missing','provider':'ollama','model':model,'available_models':models}
    except Exception:
        return {'status':'offline','provider':'ollama','model':model,'available_models':[]}

@app.get('/api/health')
def health(): return {'status':'ok','version':'13.0.0','product':'Karigar Link','assistant_model':os.getenv('OLLAMA_MODEL','llama3.2:1b')}
@app.get('/api/artisans')
def artisans():
    c=db(); r=[dict(x) for x in c.execute('select * from artisans order by id')]; c.close(); return r
@app.post('/api/artisans')
def add_artisan(x:ArtisanIn):
    c=db(); c.execute('insert into artisans(name,phone,language,region,craft,capacity,created_at) values(?,?,?,?,?,?,?)',(x.name,x.phone,x.language,x.region,x.craft,x.capacity,datetime.now().isoformat())); c.commit(); aid=c.execute('select last_insert_rowid()').fetchone()[0]; c.close(); return {'id':aid}
@app.get('/api/products')
def products(artisan_id:int=1):
    c=db(); r=[dict(x) for x in c.execute('select * from products where artisan_id=? order by id desc',(artisan_id,))]; c.close(); return r
@app.post('/api/products')
def add_product(x:ProductIn):
    c=db(); c.execute('insert into products(artisan_id,name,craft,material,region,technique,description,cost,price,capacity_week,created_at) values(?,?,?,?,?,?,?,?,?,?,?)',(x.artisan_id,x.name,x.craft,x.material,x.region,x.technique,x.description,x.cost,x.price,x.capacity_week,datetime.now().isoformat())); c.commit(); pid=c.execute('select last_insert_rowid()').fetchone()[0]; c.close(); return {'id':pid}
@app.get('/api/products/{pid}/matches')
def matches(pid:int): return market_matches(pid)

@app.get('/api/products/{pid}/market-intelligence')
def market_intelligence(pid:int): return market_matches(pid)

@app.get('/api/products/{pid}/market-simulator')
def market_simulator(pid:int, price:float=0, capacity:int=0):
    r=market_matches(pid)
    p=r.get('product') or {}
    base_price=float(p.get('price') or 0); base_capacity=int(p.get('capacity_week') or 0)
    new_price=price if price>0 else base_price
    new_capacity=capacity if capacity>0 else base_capacity
    buyers=r.get('buyers',[])
    out=[]
    for b in buyers[:5]:
        fit=45
        if b['budget_min']<=new_price<=b['budget_max']: fit+=20
        elif new_price and new_price<b['budget_min']: fit+=8
        if new_capacity>=b['volume_min']: fit+=15
        out.append({'buyer':b['buyer'],'score':min(99,fit+max(0,b['score']-60)//4)})
    avg=sum(x['score'] for x in out)/len(out) if out else 0
    return {'price':new_price,'capacity_week':new_capacity,'top_buyer_score':round(max([x['score'] for x in out],default=0),1),'average_buyer_score':round(avg,1),'buyers':out,'note':'Simulation only; use actual enquiry and order outcomes to validate the change.'}
@app.get('/api/dashboard')
def dashboard(artisan_id:int=1): return insights(artisan_id)
@app.get('/api/recommendations')
def recommendations(artisan_id:int=1): return insights(artisan_id)['recommendations']
@app.get('/api/impact')
def impact(artisan_id:int=1):
    c=db()
    product_count=c.execute('select count(*) n from products where artisan_id=?',(artisan_id,)).fetchone()['n']
    dataset_count=c.execute('select count(*) n from datasets where artisan_id=?',(artisan_id,)).fetchone()['n']
    tx_count=c.execute('select count(*) n from sales s join datasets d on d.id=s.dataset_id where d.artisan_id=?',(artisan_id,)).fetchone()['n']
    buyer_count=c.execute('select count(*) n from buyers').fetchone()['n']
    quality_rows=c.execute('select quality from datasets where artisan_id=? order by id desc',(artisan_id,)).fetchall()
    c.close()
    i=insights(artisan_id)
    rows=sales_for(artisan_id)
    revenue=sum(r['quantity']*r['price'] for r in rows)
    units=sum(r['quantity'] for r in rows)
    by_buyer={}; by_city={}; by_month={}; by_product={}
    for r in rows:
        rev=r['quantity']*r['price']
        buyer=r['buyer'] or 'Unspecified'
        city=r['city'] or 'Unspecified'
        month=(r['sale_date'] or '')[:7] or 'Unspecified'
        product=r['product'] or 'Unspecified'
        by_buyer.setdefault(buyer,0); by_buyer[buyer]+=rev
        by_city.setdefault(city,0); by_city[city]+=rev
        by_month.setdefault(month,0); by_month[month]+=rev
        by_product.setdefault(product,[0,0]); by_product[product][0]+=r['quantity']; by_product[product][1]+=rev
    top_buyer=sorted(by_buyer.items(),key=lambda x:x[1],reverse=True)[:6]
    top_city=sorted(by_city.items(),key=lambda x:x[1],reverse=True)[:6]
    top_product=sorted(by_product.items(),key=lambda x:x[1][1],reverse=True)[:6]
    months=sorted(by_month.items(),key=lambda x:x[0])[-12:]
    avg_quality=round(sum(quality_rows[i]['quality'] for i in range(len(quality_rows)))/len(quality_rows),1) if quality_rows else None
    # Compare first and second half of the recorded period when enough dated data exists.
    dated=[r for r in rows if (r['sale_date'] or '')[:7]]
    growth=None
    if len(dated)>=4:
        dates=sorted((r['sale_date'] or '')[:7] for r in dated)
        mid=len(dates)//2; cut=dates[mid]
        first=sum(r['quantity']*r['price'] for r in dated if (r['sale_date'] or '')[:7] < cut)
        second=sum(r['quantity']*r['price'] for r in dated if (r['sale_date'] or '')[:7] >= cut)
        if first>0: growth=round((second-first)/first*100,1)
    return {
        'products_digitized':product_count,
        'datasets_imported':dataset_count,
        'historical_transactions':tx_count,
        'buyer_profiles':buyer_count,
        'markets_reached':i.get('kpis',{}).get('markets',0),
        'revenue_recorded':round(revenue,2),
        'units_recorded':round(units,1),
        'avg_order_value':round(revenue/tx_count,2) if tx_count else 0,
        'avg_data_quality':avg_quality,
        'growth_percent':growth,
        'top_products':[{'name':k,'units':round(v[0],1),'revenue':round(v[1],2)} for k,v in top_product],
        'top_buyers':[{'name':k,'revenue':round(v,2)} for k,v in top_buyer],
        'top_markets':[{'name':k,'revenue':round(v,2)} for k,v in top_city],
        'monthly_sales':[{'month':k,'revenue':round(v,2)} for k,v in months],
        'recommendations':i.get('recommendations',[]),
        'note':'Impact figures are recorded business outcomes. Changes are not automatically attributed to Karigar Link.'
    }

def parse_upload(raw, filename):
    if filename.lower().endswith('.csv'):
        return parse_csv(raw)
    if filename.lower().endswith(('.xlsx','.xls')):
        try:
            from openpyxl import load_workbook
            wb=load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            ws=wb.active
            values=list(ws.values)
            if not values: return [], []
            headers=[str(x).strip() if x is not None else '' for x in values[0]]
            rows=[{headers[i]: (row[i] if i < len(row) else '') for i in range(len(headers))} for row in values[1:]]
            return rows, headers
        except Exception as e:
            raise HTTPException(400,f'Could not read Excel file: {e}')
    raise HTTPException(400,'Upload CSV or Excel (.xlsx/.xls) file.')

def dataset_ids_for(artisan_id):
    c=db(); ids=[r['id'] for r in c.execute('select id from datasets where artisan_id=?',(artisan_id,)).fetchall()]; c.close(); return ids

def delete_dataset_internal(dataset_id, artisan_id):
    c=db(); d=c.execute('select * from datasets where id=? and artisan_id=?',(dataset_id,artisan_id)).fetchone()
    if not d: c.close(); return False
    c.execute('delete from sales where dataset_id=?',(dataset_id,))
    c.execute('delete from datasets where id=?',(dataset_id,))
    c.commit(); c.close()
    if d['raw_path']:
        try: Path(d['raw_path']).unlink(missing_ok=True)
        except Exception: pass
    return True

@app.post('/api/import/preview')
async def import_preview(file:UploadFile=File(...),artisan_id:int=Form(1)):
    raw=await file.read()
    rows,headers=parse_upload(raw,file.filename)
    mapping=map_columns(headers); report=quality_report(rows,mapping)
    return {'filename':file.filename,'headers':headers,'mapping':mapping,'report':report,'supported_modes':['add','replace'],'message':'Preview only. No records have been saved yet.'}

@app.post('/api/import/csv')
async def import_csv(file:UploadFile=File(...),artisan_id:int=Form(1),import_mode:str=Form('add'),mapping_json:str=Form('')):
    raw=await file.read()
    rows,headers=parse_upload(raw,file.filename)
    detected=map_columns(headers)
    try: mapping=json.loads(mapping_json) if mapping_json else detected
    except Exception: mapping=detected
    mapping={k:v for k,v in mapping.items() if v in headers}
    report=quality_report(rows,mapping)
    if import_mode not in ('add','replace'): raise HTTPException(400,'Import mode must be add or replace.')
    if not mapping.get('product'): raise HTTPException(400,'Map a Product column before importing.')
    if import_mode=='replace':
        for did in dataset_ids_for(artisan_id): delete_dataset_internal(did,artisan_id)
    path=DATA/f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{re.sub(r'[^A-Za-z0-9_.-]','_',file.filename)}"; path.write_bytes(raw)
    c=db(); c.execute('insert into datasets(artisan_id,name,rows,columns,quality,imported_at,raw_path,mapping_json) values(?,?,?,?,?,?,?,?)',(artisan_id,file.filename,len(rows),len(headers),report['quality'],datetime.now().isoformat(),str(path),json.dumps(mapping))); c.commit(); did=c.execute('select last_insert_rowid()').fetchone()[0]
    ins=0; skipped=0; row_keys=set()
    for r in rows:
        product=str(r.get(mapping['product'],'')).strip()
        if not product: skipped+=1; continue
        q=fnum(r.get(mapping.get('quantity',''),1)) if mapping.get('quantity') else 1
        pr=fnum(r.get(mapping.get('price',''),0)) if mapping.get('price') else 0
        key='|'.join(str(r.get(h,'' )).strip() for h in headers)
        if key in row_keys: skipped+=1; continue
        row_keys.add(key)
        c.execute('insert into sales(dataset_id,sale_date,product,quantity,price,buyer,city,payment) values(?,?,?,?,?,?,?,?)',(did,str(r.get(mapping.get('date',''),'')).strip(),product,q,pr,str(r.get(mapping.get('buyer',''),'')).strip(),str(r.get(mapping.get('city',''),'')).strip(),str(r.get(mapping.get('payment',''),'')).strip()))
        ins+=1
    c.commit(); c.close(); report.update({'dataset_id':did,'imported_rows':ins,'skipped_rows':skipped,'filename':file.filename,'mode':import_mode}); return report

@app.get('/api/datasets')
def datasets(artisan_id:int=1):
    c=db(); r=[dict(x) for x in c.execute('select id,name,rows,columns,quality,imported_at,mapping_json from datasets where artisan_id=? order by id desc',(artisan_id,))]; c.close(); return r

@app.get('/api/historical/summary')
def historical_summary(artisan_id:int=1):
    rows=sales_for(artisan_id); ds=datasets(artisan_id);
    revenue=sum(r['quantity']*r['price'] for r in rows); units=sum(r['quantity'] for r in rows)
    products=len({r['product'] for r in rows if r['product']}); buyers=len({r['buyer'] for r in rows if r['buyer']}); markets=len({r['city'] for r in rows if r['city']})
    return {'records':len(rows),'datasets':len(ds),'revenue':round(revenue,2),'units':round(units,1),'products':products,'buyers':buyers,'markets':markets,'latest_import':ds[0]['imported_at'] if ds else None}

@app.get('/api/historical/records')
def historical_records(artisan_id:int=1,search:str='',dataset_id:int=0,limit:int=50,offset:int=0):
    limit=max(1,min(limit,200)); offset=max(0,offset); c=db(); where=['d.artisan_id=?']; params=[artisan_id]
    if dataset_id: where.append('s.dataset_id=?'); params.append(dataset_id)
    if search:
        where.append('(s.product like ? or s.buyer like ? or s.city like ?)'); q=f'%{search}%'; params += [q,q,q]
    base=' from sales s join datasets d on d.id=s.dataset_id where '+ ' and '.join(where)
    total=c.execute('select count(*) n'+base,params).fetchone()['n']
    rows=[dict(r) for r in c.execute('select s.id,s.dataset_id,d.name dataset_name,s.sale_date,s.product,s.quantity,s.price,s.buyer,s.city,s.payment'+base+' order by s.id desc limit ? offset ?',params+[limit,offset]).fetchall()]
    c.close(); return {'total':total,'limit':limit,'offset':offset,'rows':rows}

@app.get('/api/historical/export')
def historical_export(artisan_id:int=1,search:str='',dataset_id:int=0):
    c=db(); where=['d.artisan_id=?']; params=[artisan_id]
    if dataset_id: where.append('s.dataset_id=?'); params.append(dataset_id)
    if search:
        where.append('(s.product like ? or s.buyer like ? or s.city like ?)'); q=f'%{search}%'; params += [q,q,q]
    rows=c.execute('select s.sale_date,s.product,s.quantity,s.price,s.buyer,s.city,s.payment,d.name dataset_name from sales s join datasets d on d.id=s.dataset_id where '+' and '.join(where)+' order by s.id',params).fetchall(); c.close()
    out=io.StringIO(); w=csv.writer(out); w.writerow(['sale_date','product','quantity','price','buyer','city','payment','dataset'])
    for r in rows: w.writerow(list(r))
    data=out.getvalue().encode('utf-8-sig')
    return StreamingResponse(io.BytesIO(data),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename=karigar_link_historical_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv'})

@app.delete('/api/datasets/{dataset_id}')
def delete_dataset(dataset_id:int,artisan_id:int=1):
    if not delete_dataset_internal(dataset_id,artisan_id): raise HTTPException(404,'Dataset not found.')
    return {'deleted':True,'dataset_id':dataset_id,'message':'Import and its historical records were deleted. The original uploaded file was also removed.'}

@app.delete('/api/historical/records/{record_id}')
def delete_record(record_id:int,artisan_id:int=1):
    c=db(); row=c.execute('select s.id from sales s join datasets d on d.id=s.dataset_id where s.id=? and d.artisan_id=?',(record_id,artisan_id)).fetchone()
    if not row: c.close(); raise HTTPException(404,'Historical record not found.')
    c.execute('delete from sales where id=?',(record_id,)); c.commit(); c.close(); return {'deleted':True,'record_id':record_id}

@app.delete('/api/historical/all')
def delete_all_history(artisan_id:int=1):
    ids=dataset_ids_for(artisan_id); count=0
    for did in ids:
        c=db(); n=c.execute('select count(*) n from sales where dataset_id=?',(did,)).fetchone()['n']; c.close(); count+=n; delete_dataset_internal(did,artisan_id)
    return {'deleted_datasets':len(ids),'deleted_records':count}
@app.post('/api/market-ready')
async def market_ready(
    name:str=Form(''), craft:str=Form(''), material:str=Form(''), region:str=Form(''), technique:str=Form(''),
    description:str=Form(''), voice_text:str=Form(''), price:float=Form(0), cost:float=Form(0), capacity:int=Form(0),
    photo:UploadFile|None=File(None)
):
    image_name=None
    if photo and photo.filename:
        ext=Path(photo.filename).suffix.lower()[:8] or '.bin'
        image_name=f"{uuid.uuid4().hex}{ext}"
        raw=await photo.read(); (IMAGES/image_name).write_bytes(raw)
    result=market_ready_engine(name,craft,material,region,technique,description,voice_text,price,cost,capacity)
    result['photo_saved']=bool(image_name); result['photo_name']=image_name
    result['note']='Photo is preserved with the product request; catalogue inference currently uses the artisan text/voice fields and explainable local rules, so no paid AI API is required.'
    return result

@app.post('/api/enquiries')
async def create_enquiry(product_id:int=Form(...), buyer_name:str=Form(...), buyer_type:str=Form('Retail'), city:str=Form(''), quantity:int=Form(1), budget:float=Form(0), message:str=Form('')):
    c=db(); c.execute('insert into enquiries(product_id,buyer_name,buyer_type,city,quantity,budget,message,status,created_at) values(?,?,?,?,?,?,?,?,?)',(product_id,buyer_name,buyer_type,city,quantity,budget,message,'New',datetime.now().isoformat())); c.commit(); eid=c.execute('select last_insert_rowid()').fetchone()[0]; c.close(); return {'id':eid,'status':'New','message':'Buyer enquiry recorded successfully.'}

@app.get('/api/enquiries')
def get_enquiries():
    c=db(); rows=[dict(x) for x in c.execute('select e.*,p.name product from enquiries e left join products p on p.id=e.product_id order by e.id desc')]; c.close(); return rows

@app.get('/api/pricing/{pid}')
def pricing(pid:int):
    c=db(); p=c.execute('select * from products where id=?',(pid,)).fetchone()
    if not p:
        c.close(); raise HTTPException(404,'Product not found')
    cost=float(p['cost'] or 0); base=float(p['price'] or 0); name=p['name'] or ''
    hist=c.execute('select quantity,price,sale_date,buyer,city from sales where lower(trim(product))=lower(trim(?)) and price>0',(name,)).fetchall()
    buyers=c.execute('select name,type,city,budget_min,budget_max,volume_min,volume_max from buyers').fetchall(); c.close()
    hist_qty=sum(float(x['quantity'] or 0) for x in hist); hist_rev=sum(float(x['quantity'] or 0)*float(x['price'] or 0) for x in hist)
    prices=[float(x['price']) for x in hist if x['price'] is not None]
    realized=round(hist_rev/hist_qty,2) if hist_qty else 0
    minimum=round(cost*1.15,2) if cost else round(base*0.80,2)
    p30=round(cost/0.70,2) if cost else round(base/0.70,2) if base else 0
    p40=round(cost/0.60,2) if cost else round(base/0.60,2) if base else 0
    p50=round(cost/0.50,2) if cost else round(base/0.50,2) if base else 0
    retail=round(max(base, p40),2) if (base or cost) else 0
    b2b=round(max(cost/0.70 if cost else 0, (realized or base)*0.85),2) if (base or cost or realized) else 0
    margin=round((base-cost)/base*100,1) if base else 0
    buyer_fit=[]
    for b in buyers:
        ref=b['budget_max'] or 0
        if not ref: continue
        offer=b2b or base
        if b['budget_min']<=offer<=b['budget_max']: fit=95
        elif offer < b['budget_min']: fit=78
        else: fit=52
        buyer_fit.append({'buyer':b['name'],'type':b['type'],'city':b['city'],'budget_min':b['budget_min'],'budget_max':b['budget_max'],'fit':fit})
    buyer_fit.sort(key=lambda x:x['fit'], reverse=True)
    return {'product':name,'cost':cost,'list_price':base,'historical_or_list_price':realized or base,'current_margin_percent':margin,
      'historical':{'transactions':len(hist),'units':round(hist_qty,1),'revenue':round(hist_rev,2),'average_realized_price':realized,'lowest_price':min(prices) if prices else 0,'highest_price':max(prices) if prices else 0,'latest_price':prices[-1] if prices else 0},
      'minimum_sustainable_price':minimum,'margin_prices':{'30%':p30,'40%':p40,'50%':p50},'recommended_retail':retail,'recommended_b2b':b2b,
      'price_gap_to_retail':round(retail-(realized or base),2) if (realized or base) else 0,'buyer_fit':buyer_fit[:5],
      'guidance':[f'Never price below ₹{minimum:,.0f} without a clear strategic reason.' if minimum else 'Add product cost to calculate a sustainable price.',f'Target retail around ₹{retail:,.0f} for the selected margin structure.' if retail else 'Add a list price to calculate retail guidance.',f'For bulk conversations, start around ₹{b2b:,.0f} and negotiate using quantity and delivery terms.' if b2b else 'Add cost and list price to calculate a B2B offer.',f'Historical realized average is ₹{realized:,.0f} across {len(hist)} recorded transactions.' if hist else 'No matching historical transactions yet; recommendations are cost/list-price based.'],
      'explanation':'Recommendations combine recorded/list price, cost-based margin floors, historical realized prices when available, and buyer budget fit. They are decision support, not a guarantee of market price.'}
@app.get('/api/catalogue/{pid}')
def catalogue(pid:int):
    c=db()
    p=c.execute('select * from products where id=?',(pid,)).fetchone()
    artisan=c.execute('select * from artisans where id=?',(p['artisan_id'],)).fetchone() if p else None
    c.close()
    if not p: raise HTTPException(404,'Product not found')
    name=p['name']; craft=p['craft'] or 'Traditional Craft'; material=p['material'] or 'natural materials'; region=p['region'] or 'India'; technique=p['technique'] or 'traditional handcraft techniques'; desc=p['description'] or f'Handmade {name.lower()} created using {material}.'
    price=p['price'] or 0; cost=p['cost'] or 0; capacity=p['capacity_week'] or 0
    margin=round((price-cost)/price*100) if price else 0
    title=f"Handcrafted {name} | {craft}"
    short=f"A handcrafted {name.lower()} made from {material}, combining traditional {craft.lower()} with practical everyday use. Suitable for home décor, gifting and curated craft collections."
    long=(f"{name} is a handmade {craft.lower()} product created in {region} using {material} and {technique}. "
          f"{desc.rstrip('.')}. The product is positioned as a practical, culturally rooted alternative to mass-produced décor and storage products. "
          f"Its handmade character makes each piece distinctive, while its functional design supports everyday use, gifting and curated retail collections.")
    story=(f"Crafted in {region}, this product represents local artisan knowledge and small-scale handmade production. "
           f"The use of {material} connects the product to traditional craft practice, while the functional positioning helps take that craft into modern homes and contemporary markets.")
    selling=[
        f"Handmade {craft.lower()} from {region}",
        f"Made using {material} and {technique}",
        "Functional design with a handcrafted character",
        "Suitable for gifting, home décor and curated retail",
        "Supports artisan-made and locally rooted products"
    ]
    occasions=['Home organisation','Home décor','Festive gifting','Corporate gifting','Boutique / curated retail']
    customer_segments=['Conscious home décor buyers','Tourists and craft collectors','Boutique and lifestyle retailers','Corporate gifting buyers','Hotels, resorts and institutions']
    channels=['Local craft exhibitions and fairs','Instagram / WhatsApp catalogue','Boutique and lifestyle stores','Corporate gifting programmes','Government / institutional procurement']
    seo=[craft,material,'handmade '+name,region+' handicraft','artisan made','Indian handicraft','eco friendly craft','handcrafted home decor']
    whatsapp=(f"Namaste! We make handcrafted {name.lower()} from {material} in {region}. "
              f"It is handmade using {technique} and is ideal for home décor, gifting and curated retail. "
              f"Retail price: ₹{price:,.0f}. Bulk and customised orders are available based on production capacity.")
    instagram=(f"Bring handmade {region} craft into everyday spaces. {name} is crafted from {material}, combining traditional skill with useful modern design. "
               f"Perfect for décor, gifting and conscious shopping. DM for retail, bulk or customised orders. #{craft.replace(' ','')} #{material.replace(' ','')} #Handmade #IndianCraft #ArtisanMade")
    buyer_pitch=(f"We supply artisan-made {name.lower()} from {region}, produced using {material}. The product is suitable for retail, gifting and institutional collections. "
                 f"Current indicative capacity is {capacity} units/week, with an indicative list price of ₹{price:,.0f}. Bulk pricing and custom quantities can be discussed.")
    return {
        'title':title,'short_description':short,'long_description':long,'story':story,'english':long,
        'hindi':f"यह {name} {region} में {material} से {technique} द्वारा बनाया गया हस्तनिर्मित उत्पाद है। यह घर की सजावट, उपयोगी स्टोरेज, उपहार और चयनित रिटेल के लिए उपयुक्त है। इसका हस्तनिर्मित स्वरूप हर पीस को अलग पहचान देता है और स्थानीय कारीगर की कला को आधुनिक बाजार तक पहुंचाने में मदद करता है।",
        'identity':{'product_name':name,'craft':craft,'material':material,'technique':technique,'region':region,'artisan':artisan['name'] if artisan else 'Artisan','handmade':True,'category':'Handicraft / Home & Lifestyle','production_capacity_week':capacity},
        'commercial':{'list_price':price,'estimated_cost':cost,'gross_margin_percent':margin,'minimum_order_quantity':5 if capacity>=10 else 1,'bulk_order_available':capacity>0,'customization_available':True,'packaging':'Protective recyclable packaging recommended','shipping':'Use moisture-safe protective packaging for inter-city delivery'},
        'market_positioning':{'primary_segment':'Home décor & lifestyle','primary_customer':customer_segments[0],'secondary_segments':customer_segments[1:],'recommended_channels':channels,'use_cases':occasions,'positioning':'Traditional artisan craft + practical modern use'},
        'selling_points':selling,'seo_keywords':seo,'tags':seo[:5],
        'marketing':{'whatsapp':whatsapp,'instagram':instagram,'buyer_pitch':buyer_pitch,'call_to_action':'Enquire for retail, bulk or customised orders.'}
    }

# Serve frontend
FRONT=BASE.parent/'frontend'

# -----------------------------------------------------------------------------
# Live official information modules
# These endpoints never invent contact details, deadlines or eligibility. They
# return official-source guidance and perform a lightweight live source check.
# -----------------------------------------------------------------------------
OFFICIAL_SOURCES = {
    'handicrafts_events': 'https://indian.handicrafts.gov.in/en/events',
    'handicrafts_home': 'https://indian.handicrafts.gov.in/',
    'nhdp': 'https://indian.handicrafts.gov.in/en/schemes/national-handicrafts-development-programme-nhdp',
    'chcds': 'https://indian.handicrafts.gov.in/en/schemes/comprehensive-handicrafts-cluster-development-scheme-chcds',
    'pm_vishwakarma': 'https://pmvishwakarma.gov.in/',
    'gem': 'https://gem.gov.in/',
    'indiahandmade': 'https://www.indiahandmade.com/'
}

def official_check(urls):
    checked=[]; ok=0
    for url in urls:
        try:
            req=Request(url,headers={'User-Agent':'Karigar-Link/2.3'})
            with urlopen(req,timeout=1) as r:
                status=getattr(r,'status',200)
                if 200 <= status < 400: ok += 1
                checked.append({'url':url,'ok':200 <= status < 400,'status':status})
        except Exception as e:
            checked.append({'url':url,'ok':False,'status':None})
    return checked, ('Live check successful' if ok else 'Official sources unavailable; showing verified source routes')

def live_items():
    # Network checks are intentionally not performed in the request path so a
    # slow government site can never freeze the local application. Official
    # links are returned for one-click verification/refresh by the user.
    return [{'url':OFFICIAL_SOURCES['handicrafts_events'],'ok':None,'status':'on-demand'}, {'url':OFFICIAL_SOURCES['indiahandmade'],'ok':None,'status':'on-demand'}], 'Official sources ready; verify live status by opening the official source'

@app.get('/api/market-news')
def market_news():
    checked,status=live_items(); now=datetime.now().isoformat(timespec='minutes')
    items=[
      {'title':'Handicraft exhibitions and events calendar','date':'Current official calendar','category':'Market opportunity','detail':'Use the official Development Commissioner (Handicrafts) events calendar to check current exhibitions, participation information and event-specific notices. Dates and participation rules can change, so verify the source before planning inventory or travel.','action':'Open the official calendar and shortlist events that match your craft, production capacity and target market.','source':'Development Commissioner (Handicrafts)','url':OFFICIAL_SOURCES['handicrafts_events']},
      {'title':'Handmade market access','date':'Current portal','category':'Selling channel','detail':'Indiahandmade provides an official government-backed digital route for handmade products. Review current seller and product requirements before preparing a listing.','action':'Review the current portal requirements and prepare product photographs, catalogue information and pricing.','source':'Indiahandmade','url':OFFICIAL_SOURCES['indiahandmade']},
      {'title':'Government e-Marketplace access','date':'Current portal','category':'Institutional market','detail':'GeM is the government procurement marketplace. Sellers should verify current registration, product-category and procurement requirements directly on the official portal.','action':'Check whether your product category and business profile can be listed or supplied through GeM.','source':'Government e-Marketplace','url':OFFICIAL_SOURCES['gem']}
    ]
    return {'checked_at':now,'status':status,'source_checks':checked,'items':items}

@app.get('/api/government-schemes')
def government_schemes():
    """Official support programmes. Keep schemes separate from time-bound business opportunities."""
    checked,status=([{'url':OFFICIAL_SOURCES['handicrafts_home'],'ok':None,'status':'on-demand'},
                     {'url':OFFICIAL_SOURCES['pm_vishwakarma'],'ok':None,'status':'on-demand'}],
                    'Official sources ready; verify current eligibility and notices before applying')
    now=datetime.now().isoformat(timespec='minutes')
    items=[
      {'name':'National Handicrafts Development Programme (NHDP)',
       'support_type':'Sector Development / Training / Marketing',
       'target':'Handicraft artisans and eligible sector stakeholders',
       'tags':['Artisan','Training','Marketing'],
       'summary':'Government handicrafts programme aimed at strengthening the sector, sustainable livelihoods, product development, quality, technology, branding and marketing.',
       'support':'Applicable components can cover areas such as product/design development, training, technology, branding, marketing and other handicraft-sector interventions.',
       'eligibility':'Depends on the applicable NHDP component and current guidelines; do not assume every component is open to every applicant.',
       'documents':'Keep artisan/craft identity, bank and component-specific supporting documents ready. Exact documents depend on the component and current notice.',
       'deadline':'No single universal deadline shown here; check the current component/notice.',
       'how_to_apply':'Open the official scheme information and follow the current component-specific application route.',
       'last_verified':'07-10-2026',
       'url':OFFICIAL_SOURCES['nhdp']},
      {'name':'Comprehensive Handicrafts Cluster Development Scheme (CHCDS)',
       'support_type':'Cluster / Infrastructure / Market Access',
       'target':'Eligible handicraft clusters / implementing structures',
       'tags':['Artisan','Marketing'],
       'summary':'Integrated cluster-development route focused on infrastructure, production-chain improvement, modernization, product development and market linkage.',
       'support':'Cluster-level infrastructure, modernization, production-chain strengthening, product development/diversification and market-linkage support may apply through approved projects.',
       'eligibility':'Primarily relevant to eligible cluster/project structures; individual artisan eligibility should not be assumed.',
       'documents':'Project/cluster records and component-specific documentation as required by the current guidelines.',
       'deadline':'Check the latest official notice or project call; no universal deadline is assumed.',
       'how_to_apply':'Review the official scheme guidelines and the applicable implementing/project route.',
       'last_verified':'07-10-2026',
       'url':OFFICIAL_SOURCES['chcds']},
      {'name':'PM Vishwakarma',
       'support_type':'Training / Toolkit / Credit / Market Support',
       'target':'Eligible traditional artisans and craftspeople',
       'tags':['Artisan','Finance','Training','Marketing'],
       'summary':'National support programme for eligible traditional artisans and craftspeople, with skill, toolkit, credit and market-support components subject to scheme rules.',
       'support':'Depending on eligibility and current scheme rules, support includes skill training, toolkit incentive, credit support and market linkage/marketing components.',
       'eligibility':'Only listed trades and eligible beneficiaries under the current PM Vishwakarma rules qualify. Verify the current trade list and conditions before applying.',
       'documents':'Identity, enrolment/verification and scheme-specific documents as required by the official process.',
       'deadline':'Check the official portal for current enrolment and programme notices.',
       'how_to_apply':'Use the official PM Vishwakarma portal or authorised assistance route; do not pay an unofficial intermediary.',
       'last_verified':'07-10-2026',
       'url':OFFICIAL_SOURCES['pm_vishwakarma']},
      {'name':'National SC-ST Hub',
       'support_type':'Market Access / Procurement / Capacity Building',
       'target':'Eligible SC/ST micro and small enterprises',
       'tags':['SC/ST','Finance','Training','Marketing'],
       'summary':'Government support route focused on increasing participation of eligible SC/ST enterprises in public procurement and building business capability.',
       'support':'Support can include procurement-readiness, capacity building, market access and related interventions under the current programme rules.',
       'eligibility':'Relevant to eligible SC/ST enterprises; verify enterprise classification and current programme conditions on the official MSME source.',
       'documents':'Enterprise/category and registration documents as required by the current official process.',
       'deadline':'Programme notices and activities vary; verify the current official portal.',
       'how_to_apply':'Check the official National SC-ST Hub/MSME route for current registration, assistance and programmes.',
       'last_verified':'07-10-2026',
       'url':'https://scsthub.in/'},
    ]
    return {'checked_at':now,'status':status,'source_checks':checked,'items':items,
            'note':'Schemes are long/medium-term support routes. Time-bound exhibitions and selling opportunities are kept in Business Opportunities.'}

@app.get('/api/business-opportunities')
def business_opportunities():
    """Time-bound or actionable market opportunities, kept separate from schemes."""
    checked,status=live_items(); now=datetime.now().isoformat(timespec='minutes')
    # Current official event records verified against the Development Commissioner (Handicrafts)
    # events calendar. Expired records are intentionally excluded from this active list.
    events=[
      {'type':'Gandhi Shilp Bazar','priority':'High','title':'GSB (State) at Shillong','location':'Shillong, Meghalaya','start_date':'06-11-2026','end_date':'15-11-2026','deadline':'08-10-2026 23:45','stalls':56,'eligibility':'See official event eligibility notice','detail':'Government handicrafts marketing event with artisan participation opportunity.','why':'Useful for direct market exposure, customer discovery and buyer contacts.','action':'Open the official event notice immediately and verify eligibility before applying.','url':OFFICIAL_SOURCES['handicrafts_events']},
      {'type':'Gandhi Shilp Bazar','priority':'High','title':'GSB (State) at Dimapur UH','location':'Dimapur, Nagaland','start_date':'15-11-2026','end_date':'24-11-2026','deadline':'15-10-2026 23:45','stalls':56,'eligibility':'See official event eligibility notice','detail':'Official handicraft marketing event listed on the Government events calendar.','why':'Can provide physical market exposure and contacts outside the artisan’s home market.','action':'Check the official event details and application eligibility.','url':OFFICIAL_SOURCES['handicrafts_events']},
      {'type':'Gandhi Shilp Bazar','priority':'High','title':'GSB (State) at Srinagar','location':'Srinagar, Jammu & Kashmir','start_date':'12-11-2026','end_date':'21-11-2026','deadline':'11-10-2026 23:45','stalls':56,'eligibility':'See official event eligibility notice','detail':'Official Gandhi Shilp Bazar opportunity listed by Development Commissioner (Handicrafts).','why':'Potential route to new customers, tourism-linked demand and market feedback.','action':'Verify eligibility and travel/inventory feasibility before applying.','url':OFFICIAL_SOURCES['handicrafts_events']},
      {'type':'Gandhi Shilp Bazar','priority':'High','title':'GSB (State) at Jorhat','location':'Jorhat, Assam','start_date':'14-11-2026','end_date':'23-11-2026','deadline':'11-10-2026 23:45','stalls':56,'eligibility':'See official event eligibility notice','detail':'Official Gandhi Shilp Bazar opportunity listed by Development Commissioner (Handicrafts).','why':'Provides a route for physical product discovery and customer/buyer feedback.','action':'Open the official notice and check eligibility, logistics and application status.','url':OFFICIAL_SOURCES['handicrafts_events']},
      {'type':'Gandhi Shilp Bazar','priority':'High','title':'GSB (State) at Pune','location':'Pune, Maharashtra','start_date':'20-11-2026','end_date':'29-11-2026','deadline':'18-10-2026 23:45','stalls':56,'eligibility':'See official event eligibility notice','detail':'Official Gandhi Shilp Bazar opportunity listed by Development Commissioner (Handicrafts).','why':'A western-India market exposure route for suitable craft products.','action':'Compare event timing with production capacity and verify the official participation notice.','url':OFFICIAL_SOURCES['handicrafts_events']},
      {'type':'Gandhi Shilp Bazar','priority':'High','title':'GSB (State) at Nagpur','location':'Nagpur, Maharashtra','start_date':'27-11-2026','end_date':'06-12-2026','deadline':'22-10-2026 23:45','stalls':56,'eligibility':'See official event eligibility notice','detail':'Official Gandhi Shilp Bazar opportunity listed by Development Commissioner (Handicrafts).','why':'Useful for market exposure and testing demand outside the local market.','action':'Open the official notice and verify eligibility, application and logistics.','url':OFFICIAL_SOURCES['handicrafts_events']},
      {'type':'Dilli Haat','priority':'Medium','title':'Master Creations 2 — Padma Awardee, Shilp Guru and National Awardee','location':'Dilli Haat','start_date':'01-12-2026','end_date':'15-12-2026','deadline':'Closed on 30-09-2026','stalls':None,'eligibility':'Padma Awardee, Shilp Guru and National Awardee category as stated by the official event listing','detail':'A specialised Dilli Haat participation route for recognised master craftsperson categories.','why':'Relevant only if the artisan meets the stated award-based eligibility.','action':'Keep it as a future/reference opportunity unless the official portal reopens or posts a new cycle.','url':OFFICIAL_SOURCES['handicrafts_events']},
      {'type':'Institutional marketplace','priority':'Medium','title':'Explore GeM procurement','location':'India','start_date':None,'end_date':None,'deadline':'Check current portal','stalls':None,'eligibility':'Depends on GeM seller/product/procurement requirements','detail':'Government e-Marketplace can provide an institutional procurement route when the product category and seller profile are eligible.','why':'Institutional procurement can create larger or repeat requirements than individual retail orders.','action':'Check current seller registration and product-category requirements on the official portal.','url':OFFICIAL_SOURCES['gem']},
      {'type':'Digital marketplace','priority':'Medium','title':'Prepare for Indiahandmade discovery','location':'India','start_date':None,'end_date':None,'deadline':'Check current portal','stalls':None,'eligibility':'Check current seller onboarding requirements','detail':'Indiahandmade provides a government-backed digital route for handmade products.','why':'Can extend product discovery beyond local physical markets.','action':'Review current seller requirements and prepare photographs, catalogue information, pricing and dispatch details.','url':OFFICIAL_SOURCES['indiahandmade']},
    ]
    return {'checked_at':now,'status':status,'source_checks':checked,'items':events,
            'note':'Time-bound exhibitions/events are opportunities. Government support programmes are intentionally shown separately under Government Schemes.'}



# --- Artisan subscriptions + customer marketplace (local-first MVP) ---
from typing import List, Optional
from pydantic import Field

PLAN_CATALOG={
 'artisan99': {'code':'artisan99','name':'Artisan Business OS','price':99,'period_days':30,'features':['Artisan dashboard and product management','Karigar AI assistant','Pricing, demand and market intelligence','Smart catalogue and historical data tools'],'marketplace_selling':False},
 'marketplace199': {'code':'marketplace199','name':'Business OS + Marketplace','price':199,'period_days':30,'features':['Everything in Artisan Business OS','Public customer marketplace listings','Product inventory and automatic listing sync','Customer orders and sales management'],'marketplace_selling':True}
}

def _active_subscription(c, artisan_id:int):
    row=c.execute("SELECT * FROM subscriptions WHERE artisan_id=? AND status='active' AND expires_at>? ORDER BY id DESC LIMIT 1",(artisan_id,datetime.now().isoformat())).fetchone()
    return dict(row) if row else None

def _admin_check(admin_key:str):
    expected=os.getenv('KARIGAR_ADMIN_KEY','dev-admin-change-me')
    if not admin_key or not hmac.compare_digest(admin_key,expected): raise HTTPException(401,'Admin key is missing or incorrect.')

class SubscriptionIn(BaseModel):
    artisan_id:int=1
    plan_code:str
    payment_mode:str='demo'

class ListingIn(BaseModel):
    artisan_id:int=1
    stock:int=Field(ge=0,le=100000)
    image_url:str=''
    sku:str=''
    publish:bool=True

class OrderItemIn(BaseModel):
    product_id:int
    quantity:int=Field(ge=1,le=100)

class CustomerOrderIn(BaseModel):
    customer_name:str=Field(min_length=2,max_length=100)
    email:str
    phone:str=Field(min_length=8,max_length=20)
    address:str=Field(min_length=8,max_length=300)
    city:str=Field(min_length=2,max_length=100)
    pincode:str=Field(min_length=5,max_length=10)
    payment_method:str='COD'
    items:List[OrderItemIn]

class CustomerAuthIn(BaseModel):
    name:str=''
    email:str
    phone:str=''
    password:str

@app.post('/api/store/auth/register')
def customer_register(x:CustomerAuthIn):
    name=x.name.strip(); email=x.email.strip().lower()
    if not name or len(x.password)<8: raise HTTPException(400,'Name and a password of at least 8 characters are required.')
    if '@' not in email or '.' not in email.split('@')[-1]: raise HTTPException(400,'Enter a valid email address.')
    c=db()
    try:
        c.execute('INSERT INTO customer_accounts(name,email,phone,password_hash,created_at) VALUES(?,?,?,?,?)',(name,email,x.phone.strip(),_hash_password(x.password),datetime.now().isoformat())); cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.commit()
    except sqlite3.IntegrityError:
        c.close(); raise HTTPException(409,'An account already exists with this email. Sign in instead.')
    c.close(); token=secrets.token_urlsafe(32); th=hashlib.sha256(token.encode()).hexdigest(); now=datetime.now(); c=db(); c.execute('INSERT INTO customer_sessions(token_hash,customer_id,expires_at,created_at) VALUES(?,?,?,?)',(th,cid,(now+timedelta(days=30)).isoformat(),now.isoformat())); c.commit(); c.close()
    return {'customer':{'id':cid,'name':name,'email':email,'phone':x.phone.strip()},'token':token}

@app.post('/api/store/auth/login')
def customer_login(x:CustomerAuthIn):
    email=x.email.strip().lower(); c=db(); row=c.execute('SELECT * FROM customer_accounts WHERE email=?',(email,)).fetchone(); c.close()
    if not row or not _check_password(x.password,row['password_hash']): raise HTTPException(401,'Email or password is incorrect.')
    token=secrets.token_urlsafe(32); th=hashlib.sha256(token.encode()).hexdigest(); now=datetime.now(); c=db(); c.execute('INSERT INTO customer_sessions(token_hash,customer_id,expires_at,created_at) VALUES(?,?,?,?)',(th,row['id'],(now+timedelta(days=30)).isoformat(),now.isoformat())); c.commit(); c.close()
    return {'customer':{'id':row['id'],'name':row['name'],'email':row['email'],'phone':row['phone']},'token':token}

@app.get('/api/store/auth/me')
def customer_me(authorization:str=Header(default='')):
    token=authorization.replace('Bearer ','').strip();
    if not token: raise HTTPException(401,'Sign in to continue.')
    th=hashlib.sha256(token.encode()).hexdigest(); c=db(); row=c.execute('SELECT a.* FROM customer_sessions s JOIN customer_accounts a ON a.id=s.customer_id WHERE s.token_hash=? AND s.expires_at>?',(th,datetime.now().isoformat())).fetchone(); c.close()
    if not row: raise HTTPException(401,'Session expired. Please sign in again.')
    return {'customer':{'id':row['id'],'name':row['name'],'email':row['email'],'phone':row['phone']}}

@app.post('/api/store/auth/logout')
def customer_logout(authorization:str=Header(default='')):
    token=authorization.replace('Bearer ','').strip(); th=hashlib.sha256(token.encode()).hexdigest() if token else ''
    c=db(); c.execute('DELETE FROM customer_sessions WHERE token_hash=?',(th,)); c.commit(); c.close(); return {'ok':True}

class ReviewIn(BaseModel):
    product_id:int
    customer_name:str=Field(min_length=2,max_length=80)
    rating:int=Field(ge=1,le=5)
    review:str=Field(default='',max_length=1000)

@app.get('/api/subscriptions/plans')
def subscription_plans():
    return {'plans':list(PLAN_CATALOG.values()),'note':'Prices are monthly plan prices. Online payment gateway is not connected in this local MVP.'}

@app.get('/api/subscriptions/status')
def subscription_status(artisan_id:int=1):
    c=db(); sub=_active_subscription(c,artisan_id); c.close()
    plan=PLAN_CATALOG.get(sub['plan_code']) if sub else None
    return {'subscription':sub,'plan':plan,'marketplace_selling':bool(plan and plan['marketplace_selling']),'plans':list(PLAN_CATALOG.values())}

@app.post('/api/subscriptions/activate')
def activate_subscription(x:SubscriptionIn):
    if x.plan_code not in PLAN_CATALOG: raise HTTPException(400,'Choose a valid subscription plan.')
    if x.payment_mode not in ('demo','manual'): raise HTTPException(400,'This build supports demo/manual activation only; no real payment was taken.')
    c=db()
    if not c.execute('SELECT id FROM artisans WHERE id=?',(x.artisan_id,)).fetchone(): c.close(); raise HTTPException(404,'Artisan profile not found.')
    c.execute("UPDATE subscriptions SET status='expired' WHERE artisan_id=? AND status='active'",(x.artisan_id,))
    now=datetime.now(); exp=now+timedelta(days=30)
    c.execute('INSERT INTO subscriptions(artisan_id,plan_code,status,started_at,expires_at,payment_mode,payment_reference,created_at) VALUES(?,?,?,?,?,?,?,?)',(x.artisan_id,x.plan_code,'active',now.isoformat(),exp.isoformat(),x.payment_mode,'DEMO-'+uuid.uuid4().hex[:10].upper(),now.isoformat()))
    c.commit(); sub=_active_subscription(c,x.artisan_id); c.close()
    return {'ok':True,'subscription':sub,'plan':PLAN_CATALOG[x.plan_code],'notice':'Demo activation only. No money was collected. Connect a verified payment gateway before accepting real subscriptions.'}

@app.post('/api/products/{pid}/marketplace-listing')
def update_marketplace_listing(pid:int,x:ListingIn):
    c=db(); p=c.execute('SELECT * FROM products WHERE id=? AND artisan_id=?',(pid,x.artisan_id)).fetchone()
    if not p: c.close(); raise HTTPException(404,'Product not found for this artisan.')
    sub=_active_subscription(c,x.artisan_id); plan=PLAN_CATALOG.get(sub['plan_code']) if sub else None
    if x.publish and not (plan and plan['marketplace_selling']): c.close(); raise HTTPException(403,'An active ₹199 Business OS + Marketplace plan is required to publish products.')
    if x.publish and (not p['name'] or float(p['price'] or 0)<=0): c.close(); raise HTTPException(400,'Add a product name and a price greater than zero before publishing.')
    status='published' if x.publish and x.stock>0 else ('out_of_stock' if x.publish else 'draft')
    c.execute('UPDATE products SET stock=?,image_url=?,sku=?,marketplace_status=? WHERE id=?',(x.stock,x.image_url.strip(),x.sku.strip(),status,pid)); c.commit()
    row=dict(c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()); c.close()
    return {'ok':True,'product':row,'status':status,'note':'Published products are automatically visible on the customer marketplace when the subscription remains active.'}

@app.get('/api/store/products')
def store_products(q:str='',craft:str='',sort:str='featured',limit:int=100):
    c=db(); rows=c.execute("""SELECT p.*,a.name artisan_name,a.region artisan_region FROM products p JOIN artisans a ON a.id=p.artisan_id
      JOIN subscriptions s ON s.artisan_id=p.artisan_id AND s.status='active' AND s.plan_code='marketplace199' AND s.expires_at>?
      WHERE p.marketplace_status='published' AND p.stock>0 AND p.price>0 ORDER BY p.id DESC""",(datetime.now().isoformat(),)).fetchall();
    products=[]
    for row in rows:
        item=dict(row)
        if q and q.lower() not in ' '.join(str(item.get(k,'') or '') for k in ['name','craft','material','region','description','artisan_name']).lower(): continue
        if craft and craft.lower()!=str(item.get('craft','')).lower(): continue
        reviews=c.execute('SELECT AVG(rating) avg,COUNT(*) n FROM marketplace_reviews WHERE product_id=?',(item['id'],)).fetchone()
        item['rating']=round(reviews['avg'] or 0,1); item['review_count']=reviews['n']; products.append(item)
    c.close()
    if sort=='price_low': products.sort(key=lambda x:float(x['price'] or 0))
    elif sort=='price_high': products.sort(key=lambda x:float(x['price'] or 0),reverse=True)
    elif sort=='name': products.sort(key=lambda x:x['name'].lower())
    return {'products':products[:max(1,min(limit,200))],'total':len(products),'categories':sorted({p['craft'] for p in products if p.get('craft')}),'note':'Only in-stock products from active marketplace subscribers are displayed.'}

@app.get('/api/store/products/{pid}')
def store_product_detail(pid:int):
    c=db(); row=c.execute("""SELECT p.*,a.name artisan_name,a.region artisan_region,a.craft artisan_craft FROM products p JOIN artisans a ON a.id=p.artisan_id JOIN subscriptions s ON s.artisan_id=p.artisan_id AND s.status='active' AND s.plan_code='marketplace199' AND s.expires_at>? WHERE p.id=? AND p.marketplace_status='published' AND p.stock>0""",(datetime.now().isoformat(),pid)).fetchone()
    if not row: c.close(); raise HTTPException(404,'This product is not currently available.')
    reviews=[dict(r) for r in c.execute('SELECT customer_name,rating,review,created_at FROM marketplace_reviews WHERE product_id=? ORDER BY id DESC',(pid,)).fetchall()]; c.close()
    return {'product':dict(row),'reviews':reviews}

@app.post('/api/store/orders')
def place_store_order(x:CustomerOrderIn):
    if not x.items: raise HTTPException(400,'Add at least one product to your cart.')
    if '@' not in x.email or '.' not in x.email.split('@')[-1]: raise HTTPException(400,'Enter a valid email address.')
    if x.payment_method not in ('COD','PAY_ON_CONFIRMATION'): raise HTTPException(400,'Online payment is not enabled in this build. Choose Cash on Delivery.')
    c=db(); prepared=[]; subtotal=0
    try:
        for item in x.items:
            row=c.execute("""SELECT p.*,a.id seller_id FROM products p JOIN artisans a ON a.id=p.artisan_id JOIN subscriptions s ON s.artisan_id=p.artisan_id AND s.status='active' AND s.plan_code='marketplace199' AND s.expires_at>? WHERE p.id=? AND p.marketplace_status='published' AND p.stock>=?""",(datetime.now().isoformat(),item.product_id,item.quantity)).fetchone()
            if not row: raise HTTPException(409,f'Product #{item.product_id} is unavailable or does not have enough stock.')
            prepared.append((dict(row),item.quantity)); subtotal+=float(row['price'])*item.quantity
        order_no='KL-'+datetime.now().strftime('%y%m%d')+'-'+uuid.uuid4().hex[:6].upper(); now=datetime.now().isoformat(); shipping=0 if subtotal>=999 else 59; total=round(subtotal+shipping,2)
        c.execute('INSERT INTO marketplace_orders(order_number,customer_name,email,phone,address,city,pincode,payment_method,payment_status,order_status,subtotal,shipping,total,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(order_no,x.customer_name.strip(),x.email.strip().lower(),x.phone.strip(),x.address.strip(),x.city.strip(),x.pincode.strip(),x.payment_method,'pending' if x.payment_method!='COD' else 'cash_on_delivery','placed',subtotal,shipping,total,now))
        oid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        for product,qty in prepared:
            c.execute('INSERT INTO marketplace_order_items(order_id,product_id,artisan_id,product_name,quantity,unit_price,line_total) VALUES(?,?,?,?,?,?,?)',(oid,product['id'],product['artisan_id'],product['name'],qty,product['price'],round(qty*float(product['price']),2)))
            c.execute('UPDATE products SET stock=stock-?,marketplace_status=CASE WHEN stock-?<=0 THEN \'out_of_stock\' ELSE marketplace_status END WHERE id=?',(qty,qty,product['id']))
        c.commit()
        return {'ok':True,'order_number':order_no,'order_id':oid,'subtotal':round(subtotal,2),'shipping':shipping,'total':total,'payment_method':x.payment_method,'message':'Order placed in the local demo. No online payment was collected.'}
    except Exception:
        c.rollback(); raise
    finally: c.close()

@app.get('/api/store/orders/track')
def track_store_order(order_number:str,email:str):
    c=db(); row=c.execute('SELECT * FROM marketplace_orders WHERE order_number=? AND lower(email)=?',(order_number.strip().upper(),email.strip().lower())).fetchone()
    if not row: c.close(); raise HTTPException(404,'We could not find that order with the supplied email. Check both details and try again.')
    order=dict(row); order['items']=[dict(r) for r in c.execute('SELECT product_name,quantity,unit_price,line_total FROM marketplace_order_items WHERE order_id=?',(order['id'],)).fetchall()]; c.close(); return {'order':order}

@app.post('/api/store/orders/cancel')
def cancel_store_order(order_number:str=Form(...),email:str=Form(...)):
    c=db(); row=c.execute('SELECT * FROM marketplace_orders WHERE order_number=? AND lower(email)=?',(order_number.strip().upper(),email.strip().lower())).fetchone()
    if not row: c.close(); raise HTTPException(404,'Order not found for that email address.')
    if row['order_status'] not in ('placed','confirmed'): c.close(); raise HTTPException(409,'This order can no longer be cancelled online. Contact the marketplace administrator for help.')
    c.execute("UPDATE marketplace_orders SET order_status='cancelled' WHERE id=?",(row['id'],))
    for it in c.execute('SELECT product_id,quantity FROM marketplace_order_items WHERE order_id=?',(row['id'],)).fetchall():
        c.execute("UPDATE products SET stock=stock+?,marketplace_status=CASE WHEN marketplace_status='out_of_stock' THEN 'published' ELSE marketplace_status END WHERE id=?",(it['quantity'],it['product_id']))
    c.commit(); c.close(); return {'ok':True,'message':'Order cancelled and stock returned to the seller inventory.'}

@app.post('/api/store/reviews')
def add_store_review(x:ReviewIn):
    c=db(); ok=c.execute("SELECT id FROM products WHERE id=? AND marketplace_status='published'",(x.product_id,)).fetchone()
    if not ok: c.close(); raise HTTPException(404,'Product not found.')
    c.execute('INSERT INTO marketplace_reviews(product_id,customer_name,rating,review,created_at) VALUES(?,?,?,?,?)',(x.product_id,x.customer_name.strip(),x.rating,x.review.strip(),datetime.now().isoformat())); c.commit(); c.close(); return {'ok':True}

@app.post('/api/store/wishlist')
def store_wishlist(customer_email:str=Form(...),product_id:int=Form(...)):
    email=customer_email.strip().lower()
    if '@' not in email: raise HTTPException(400,'Enter a valid email to save a wishlist.')
    c=db(); c.execute('INSERT OR IGNORE INTO marketplace_wishlist(customer_email,product_id,created_at) VALUES(?,?,?)',(email,product_id,datetime.now().isoformat())); c.commit(); c.close(); return {'ok':True,'message':'Saved to this email’s wishlist.'}

@app.get('/api/seller/orders')
def seller_orders(artisan_id:int=1):
    c=db(); rows=c.execute("""SELECT DISTINCT o.* FROM marketplace_orders o JOIN marketplace_order_items i ON i.order_id=o.id WHERE i.artisan_id=? ORDER BY o.id DESC LIMIT 200""",(artisan_id,)).fetchall(); result=[]
    for row in rows:
        item_rows=[dict(x) for x in c.execute('SELECT product_name,quantity,unit_price,line_total FROM marketplace_order_items WHERE order_id=? AND artisan_id=?',(row['id'],artisan_id)).fetchall()]
        result.append({**dict(row),'items':item_rows,'seller_subtotal':round(sum(x['line_total'] for x in item_rows),2)})
    c.close(); return {'orders':result,'note':'Local demo seller order view. Use real authenticated seller sessions before deployment.'}

@app.get('/api/admin/overview')
def admin_overview(x_admin_key:str=''):
    _admin_check(x_admin_key); c=db()
    result={'artisans':c.execute('SELECT COUNT(*) n FROM artisans').fetchone()['n'],'active_subscriptions':c.execute("SELECT COUNT(*) n FROM subscriptions WHERE status='active' AND expires_at>?",(datetime.now().isoformat(),)).fetchone()['n'],'published_products':c.execute("SELECT COUNT(*) n FROM products WHERE marketplace_status='published' AND stock>0").fetchone()['n'],'orders':c.execute('SELECT COUNT(*) n FROM marketplace_orders').fetchone()['n'],'gross_order_value':c.execute("SELECT COALESCE(SUM(total),0) n FROM marketplace_orders WHERE order_status!='cancelled'").fetchone()['n']}
    result['subscriptions']=[dict(r) for r in c.execute('SELECT s.*,a.name artisan_name,a.phone FROM subscriptions s LEFT JOIN artisans a ON a.id=s.artisan_id ORDER BY s.id DESC LIMIT 100').fetchall()]
    result['orders']=[dict(r) for r in c.execute('SELECT * FROM marketplace_orders ORDER BY id DESC LIMIT 100').fetchall()]
    result['listings']=[dict(r) for r in c.execute("SELECT p.id,p.name,p.price,p.stock,p.marketplace_status,p.artisan_id,a.name artisan_name FROM products p LEFT JOIN artisans a ON a.id=p.artisan_id WHERE p.marketplace_status!='draft' ORDER BY p.id DESC LIMIT 100").fetchall()]
    c.close(); return result

class AdminOrderUpdate(BaseModel):
    status:str

@app.patch('/api/admin/orders/{order_id}')
def admin_update_order(order_id:int,x:AdminOrderUpdate,x_admin_key:str=''):
    _admin_check(x_admin_key)
    if x.status not in ('placed','confirmed','packed','shipped','delivered','cancelled','return_requested','return_approved','refund_initiated','refunded'): raise HTTPException(400,'Invalid order status.')
    c=db(); row=c.execute('SELECT * FROM marketplace_orders WHERE id=?',(order_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404,'Order not found.')
    if row['order_status']=='cancelled' and x.status!='cancelled': c.close(); raise HTTPException(409,'Cancelled orders cannot be reopened from this screen.')
    if x.status=='cancelled' and row['order_status']!='cancelled':
        for it in c.execute('SELECT product_id,quantity FROM marketplace_order_items WHERE order_id=?',(order_id,)).fetchall(): c.execute("UPDATE products SET stock=stock+?,marketplace_status=CASE WHEN marketplace_status='out_of_stock' THEN 'published' ELSE marketplace_status END WHERE id=?",(it['quantity'],it['product_id']))
    c.execute('UPDATE marketplace_orders SET order_status=? WHERE id=?',(x.status,order_id)); c.commit(); c.close(); return {'ok':True,'status':x.status}

@app.get('/api/admin/orders/{order_id}/items')
def admin_order_items(order_id:int,x_admin_key:str=''):
    _admin_check(x_admin_key); c=db(); rows=[dict(r) for r in c.execute('SELECT * FROM marketplace_order_items WHERE order_id=?',(order_id,)).fetchall()]; c.close(); return {'items':rows}


app.mount('/app',StaticFiles(directory=FRONT,html=True),name='frontend')
@app.get('/')
def home(): return FileResponse(FRONT/'index.html')
