#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, json, time, hashlib, urllib.request, urllib.error
from html.parser import HTMLParser
from datetime import datetime, date, timedelta

# --- YAML (pyyaml) ---
try:
    import yaml
except ImportError:
    raise SystemExit("Instale pyyaml: pip install pyyaml")

# ------------ HTML -> texto ------------
class TextExtractor(HTMLParser):
    def __init__(self): super().__init__(); self._chunks=[]
    def handle_data(self, data): 
        if data: self._chunks.append(data)
    def get_text(self): return " ".join(self._chunks)

def html_to_text(html:str)->str:
    p=TextExtractor(); p.feed(html); return p.get_text()

# ------------ Datas (PT/ES/EN) ------------
PT_MONTHS = {'janeiro':1,'fevereiro':2,'março':3,'marco':3,'abril':4,'maio':5,'junho':6,'julho':7,'agosto':8,'setembro':9,'outubro':10,'novembro':11,'dezembro':12}
ES_MONTHS = {'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,'julio':7,'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,'noviembre':11,'diciembre':12}
EN_MONTHS = {'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,'july':7,'august':8,'september':9,'october':10,'november':11,'december':12}

DATE_PATTERNS = [
    # 10/11/2026, 10-11-2026
    (re.compile(r'\b([0-3]?\d)/\-\./\-\.\b'), 'dmy_numeric'),
    # 10 de janeiro de 2026 (PT)
    (re.compile(r'\b([0-3]?\d)\s+de\s+([a-zçãéíóú]+)\s+de\s+(\d{4})\b', re.IGNORECASE), 'pt_long'),
    # 10 de marzo de 2026 (ES)
    (re.compile(r'\b([0-3]?\d)\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\b', re.IGNORECASE), 'es_long'),
    # January 10, 2026 (EN)
    (re.compile(r'\b([A-Za-z]+)\s+([0-3]?\d),\s*(\d{4})\b'), 'en_long'),
    # 10 Jan 2026
    (re.compile(r'\b([0-3]?\d)\s+([A-Za-z]{3,})[,]?\s+(\d{4})\b'), 'day_mon_any'),
]

OPENING_PHRASES = [
    # EN
    re.compile(r'\bregistration(s)? (will )?open(s)? on\s+([A-Za-z]+ \d{1,2}, \d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4})', re.IGNORECASE),
    re.compile(r'\bopens on\s+([A-Za-z]+ \d{1,2}, \d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4})', re.IGNORECASE),
    # ES
    re.compile(r'\b(la|las)\s+inscripciones?\s+(se\s+)?abr(ir[aá]n|en)\s+el\s+(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4})', re.IGNORECASE),
    re.compile(r'\bapertura de inscripciones\s+(el|en)\s+(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4})', re.IGNORECASE),
    # PT
    re.compile(r'\b(inscri[cç][õo]es?)\s+(abrem|abrir[aã]o)\s+em\s+(\d{1,2}\s+de\s+[a-zçãéíóú]+\s+de\s+\d{4})', re.IGNORECASE),
]

def parse_date_fragment(fragment:str)->date|None:
    t=fragment.lower()
    # tenta padrões diretos nas frases
    for pat in DATE_PATTERNS:
        kind=pat[1]
        for m in pat[0].finditer(t):
            try:
                if kind=='dmy_numeric':
                    d,mn,y= int(m.group(1)), int(m.group(2)), int(m.group(3))
                elif kind=='pt_long':
                    d,mon,y= int(m.group(1)), m.group(2), int(m.group(3))
                    mn= PT_MONTHS.get(mon, PT_MONTHS.get(mon.replace('ç','c').replace('ã','a'), None))
                    if not mn: continue
                elif kind=='es_long':
                    d,mon,y= int(m.group(1)), m.group(2), int(m.group(3)); mn= ES_MONTHS.get(mon, None)
                    if not mn: continue
                elif kind=='en_long':
                    mon,d,y= m.group(1), int(m.group(2)), int(m.group(3)); mn= EN_MONTHS.get(mon.lower(), None)
                    if not mn: continue
                elif kind=='day_mon_any':
                    d,mon,y= int(m.group(1)), m.group(2), int(m.group(3))
                    mn= EN_MONTHS.get(mon.lower()) or PT_MONTHS.get(mon.lower()) or ES_MONTHS.get(mon.lower())
                    if not mn: continue
                else: 
                    continue
                return date(y,mn,d)
            except Exception:
                continue
    return None

def extract_opening_date(text:str)->date|None:
    for pat in OPENING_PHRASES:
        m=pat.search(text)
        if m:
            # a data pode estar no último grupo ou nos últimos 1-2 grupos; unimos e tentamos parsear
            frag=" ".join(g for g in m.groups() if g)
            d= parse_date_fragment(frag)
            if d: return d
    return None

# ------------ HTTP ------------
def fetch_url(url:str, timeout=25)->str:
    req= urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 (race-agent/1.0)'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(resp.headers.get_content_charset() or 'utf-8', errors='ignore')

# ------------ util ------------
def days_until(d:date)->int: return (d - date.today()).days
def load_yaml(path='events.yml'): 
    with open(path,'r',encoding='utf-8') as f: return yaml.safe_load(f) or {}
def load_state(path='state.json'):
    if os.path.exists(path):
        with open(path,'r',encoding='utf-8') as f: return json.load(f)
    return {"last":{}}
def save_state(state, path='state.json'):
    with open(path,'w',encoding='utf-8') as f: json.dump(state,f,ensure_ascii=False,indent=2)

def norm(s:str)->str: return re.sub(r'\s+',' ', s or '').strip().lower()

def hash_content(text:str)->str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]

# ------------ Notificações ------------
def post_to_teams(webhook_url:str, title:str, text:str, link:str=None):
    if not webhook_url: 
        print("(sem TEAMS_WEBHOOK_URL)"); return
    payload = {
        "@type":"MessageCard","@context":"http://schema.org/extensions",
        "summary": title, "themeColor":"0078D7",
        "title": title,
        "text": text + (f"\n\nVer página" if link else "")
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15): pass
    except Exception as e:
        print("Falha Teams:", e)

def send_email(cfg, subject, body):
    host=cfg.get('SMTP_HOST'); to=cfg.get('ALERT_EMAIL_TO')
    if not (host and to): return
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(body, _charset="utf-8")
    msg['Subject']=subject; msg['From']= cfg.get('SMTP_FROM') or cfg.get('SMTP_USER','bot@local'); msg['To']=to
    with smtplib.SMTP(host, int(cfg.get('SMTP_PORT','587'))) as s:
        s.starttls()
        if cfg.get('SMTP_USER') and cfg.get('SMTP_PASS'):
            s.login(cfg.get('SMTP_USER'), cfg.get('SMTP_PASS'))
        s.sendmail(msg['From'], [to], msg.as_string())

# ------------ Núcleo ------------
def main():
    cfg= load_yaml()
    window_days= int(cfg.get('window_days', 30))
    dedupe_days= int(cfg.get('dedupe_days', 3))
    events= cfg.get('events', [])
    env = {
        'TEAMS_WEBHOOK_URL': os.environ.get('TEAMS_WEBHOOK_URL',''),
        'ALERT_EMAIL_TO': os.environ.get('ALERT_EMAIL_TO',''),
        'SMTP_HOST': os.environ.get('SMTP_HOST',''),
        'SMTP_PORT': os.environ.get('SMTP_PORT','587'),
        'SMTP_USER': os.environ.get('SMTP_USER',''),
        'SMTP_PASS': os.environ.get('SMTP_PASS',''),
        'SMTP_FROM': os.environ.get('SMTP_FROM',''),
    }
    state= load_state()

    for ev in events:
        name= ev.get('name'); urls= ev.get('urls',[])
        kw_any= [norm(k) for k in ev.get('keywords_any',[])]
        kw_block= [norm(k) for k in ev.get('keywords_block',[])]
        locale_hint= ev.get('locale','en')

        for url in urls:
            try:
                html= fetch_url(url)
                text= html_to_text(html)
                low = norm(text)

                # status: aberto/fechado
                hit_any = [k for k in kw_any if k and k in low]
                hit_block = [k for k in kw_block if k and k in low]

                # possível data explícita de abertura
                d_open = extract_opening_date(text)
                reason = None

                # bloqueia se só encontrou termos de fechado
                if hit_block and not hit_any and not d_open:
                    status = "closed"
                    reason = f"Status indica fechamento ({', '.join(hit_block)})."
                    notify = False
                else:
                    notify = False
                    if d_open:
                        delta = days_until(d_open)
                        if delta >= 0 and delta <= window_days:
                            notify = True
                            reason = f"Abertura de inscrições detectada: **{d_open.strftime('%d/%m/%Y')}** (faltam {delta} dias)."
                    if not notify and hit_any:
                        notify = True
                        reason = f"Palavras‑chave encontradas: {', '.join(hit_any)}."

                # dedupe por (url + razão)
                if notify:
                    sig = hash_content(f"{url}|{reason}")
                    last_info = state["last"].get(url)
                    now = datetime.utcnow()
                    if last_info:
                        last_sig = last_info.get("sig"); last_when = last_info.get("when")
                        try:
                            last_dt = datetime.fromisoformat(last_when) if last_when else None
                        except Exception:
                            last_dt = None
                        if last_sig == sig and last_dt and (now - last_dt) < timedelta(days=dedupe_days):
                            print(f"Dedup: {name} @ {url} — já alertado recentemente.")
                            time.sleep(1); continue

                    title = f"[ALERTA] {name} — inscrições"
                    body  = f"{reason}\nFonte: {url}"
                    post_to_teams(env['TEAMS_WEBHOOK_URL'], title, body, link=url)
                    send_email(env, title, body)
                    state["last"][url] = {"sig": sig, "when": now.isoformat()}
                    print(f"Notificado: {name} @ {url} — {reason}")
                else:
                    print(f"Sem novidade: {name} @ {url}")

                time.sleep(1)  # cortesia
            except urllib.error.HTTPError as e:
                print(f"HTTPError {e.code} ao acessar {url}")
            except Exception as e:
                print(f"Erro ao processar {url}: {e}")

    save_state(state)

if __name__=="__main__":
    main()
