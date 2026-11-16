import json, os, statistics, threading, time
from collections import Counter
import paho.mqtt.client as mqtt
from flask import Flask, jsonify

BROKER = os.getenv("BROKER", "localhost")
PORT = int(os.getenv("PORT", "8080"))

lock = threading.Lock()
temps = {}     # id -> liste des temp reçues
votes = {}     # votant -> suspect
pensees = {}   # id -> {suspect, texte} : soupcon du tour en cours
debat = []     # accusations finales, dans l'ordre
roles = {}     # id -> rôle (caché jusqu'à la fin de la partie)
journal = []   # derniers événements
fini = False
dernier_role = 0

def log(txt):
    journal.append({"t": time.strftime("%H:%M:%S"), "txt": txt})
    del journal[:-40]

def reset():
    global fini
    temps.clear(); votes.clear(); pensees.clear(); debat.clear(); roles.clear()
    fini = False
    log("nouvelle partie")

def on_connect(c, u, flags, rc, props=None):
    c.subscribe("iot/#")

def on_message(c, u, msg):
    global fini, dernier_role
    p = msg.topic.split("/")
    txt = msg.payload.decode(errors="replace").strip()
    if len(p) < 3 or not txt:
        return
    with lock:
        if p[1] == "role":
            # nouvelle rafale = nouvelle partie (on oublie aussi les anciens messages retenus)
            if not msg.retain and time.time() - dernier_role > 5:
                reset()
            if not msg.retain:
                dernier_role = time.time()
            roles[p[2]] = txt
        elif p[1] == "capteurs" and p[-1] == "temperature":
            try:
                temps.setdefault(p[2], []).append(float(txt))
            except ValueError:
                return
            log(f"{p[2]} mesure {txt} °C")
        elif p[1] in ("soupcon", "debat"):
            try:
                d = json.loads(txt)
                d = {"id": p[2], "suspect": d.get("suspect"), "texte": str(d["texte"])}
            except (ValueError, KeyError, TypeError, AttributeError):
                return
            if p[1] == "soupcon":
                pensees[p[2]] = d
            else:
                debat.append(d)
            log(("%s accuse : " if p[1] == "debat" else "%s pense : ") % p[2] + d["texte"])
        elif p[1] == "votes":
            votes[p[2]] = txt
            log(f"{p[2]} vote contre {txt}")
            if roles and all(i in votes for i in roles):
                fini = True

def soupcons():
    # écart moyen à la médiane du tour + instabilité des valeurs du capteur
    s = {}
    n = max((len(v) for v in temps.values()), default=0)
    for i, v in temps.items():
        ecarts = []
        for k in range(len(v)):
            tour = [w[k] for w in temps.values() if len(w) > k]
            ecarts.append(abs(v[k] - statistics.median(tour)))
        s[i] = round(statistics.mean(ecarts) + (max(v) - min(v)), 2) if n else 0
    return s

app = Flask(__name__)

@app.get("/state")
def state():
    with lock:
        ids = sorted(set(temps) | set(roles) | set(votes) | set(pensees))
        d = {"ids": ids, "temps": temps, "votes": votes, "pensees": pensees, "debat": debat,
             "soupcons": soupcons(), "journal": journal, "attendus": len(roles),
             "fini": fini}
        if fini:
            espion = next((i for i, r in roles.items() if r == "espion"), None)
            designe, nb = Counter(votes[i] for i in roles).most_common(1)[0]
            d.update(espion=espion, designe=designe,
                     gagne=designe == espion and nb > len(roles) / 2)
        return jsonify(d)

@app.get("/")
def index():
    return PAGE

PAGE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Salle de contrôle</title>
<style>
:root{--bg:#06110d;--panel:#0b1a14;--line:#1d4a36;--fg:#b9f5d0;--dim:#5c8f76;--ok:#3dffa0;--bad:#ff4d5e;--warn:#ffc857}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 ui-monospace,Menlo,Consolas,monospace}
header{display:flex;justify-content:space-between;align-items:baseline;padding:12px 18px;border-bottom:1px solid var(--line)}
h1{margin:0;font-size:16px;letter-spacing:.2em}
#phase{color:var(--warn)}
main{display:grid;grid-template-columns:minmax(320px,1fr) minmax(320px,1fr);gap:14px;padding:14px}
@media(max-width:800px){main{grid-template-columns:1fr}}
section{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px}
h2{margin:0 0 8px;font-size:12px;color:var(--dim);letter-spacing:.15em;font-weight:normal}
svg{width:100%;height:auto;display:block;overflow:visible}
#sweep{transform-origin:200px 200px;animation:tour 4s linear infinite}
@keyframes tour{to{transform:rotate(360deg)}}
.pulse{animation:pulse 1s ease-in-out infinite}
@keyframes pulse{50%{opacity:.25}}
#journal{height:210px;overflow:auto;font-size:12px}
#journal div{padding:2px 0;border-bottom:1px dotted #143225}
#journal span{color:var(--dim);margin-right:8px}
.bar{display:grid;grid-template-columns:minmax(90px,auto) 1fr 50px;gap:8px;align-items:center;margin:5px 0}
.bar i{display:block;height:10px;border-radius:2px}
.bar div{background:#10261d;border-radius:2px}
.bulle{margin:6px 0;padding:8px 10px;border-left:3px solid;background:#10261d;border-radius:0 4px 4px 0}
.bulle b{display:block;font-size:12px;margin-bottom:2px}
.bulle.acc{background:#2a1418}
.vide{color:var(--dim)}
#verdict{display:none;margin:14px;padding:16px;text-align:center;font-size:20px;letter-spacing:.15em;border:2px solid;border-radius:6px}
.col{display:grid;gap:14px;align-content:start}
</style></head><body>
<header><h1>SALLE DE CONTRÔLE — CHASSE À L'ESPION</h1><div id="phase">connexion…</div></header>
<div id="verdict"></div>
<main>
 <section><h2>RADAR DES CAPTEURS</h2>
  <svg viewBox="0 0 400 400" id="radar">
   <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#3dffa0" stop-opacity="0"/><stop offset="1" stop-color="#3dffa0" stop-opacity=".35"/></linearGradient>
    <marker id="fl" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#ffc857"/></marker>
   </defs>
   <g fill="none" stroke="#1d4a36"><circle cx="200" cy="200" r="180"/><circle cx="200" cy="200" r="130"/><circle cx="200" cy="200" r="70"/><path d="M20 200H380M200 20V380"/></g>
   <path id="sweep" d="M200 200L200 20A180 180 0 0 1 327 73z" fill="url(#g)"/>
   <g id="fleches"></g><g id="noeuds"></g>
  </svg>
 </section>
 <div class="col">
  <section><h2 id="titrebulles">CE QUE PENSENT LES CAPTEURS</h2><div id="bulles"></div></section>
  <section><h2>TEMPÉRATURES PAR TOUR (°C)</h2><svg viewBox="0 0 400 170" id="courbes"></svg></section>
  <section><h2>NIVEAU DE SOUPÇON</h2><div id="barres"></div></section>
  <section><h2>JOURNAL</h2><div id="journal"></div></section>
 </div>
</main>
<script>
const NS="http://www.w3.org/2000/svg", COUL=["#3dffa0","#57c7ff","#ffc857","#ff8fd8","#c9a0ff","#ff9d57"];
const $=id=>document.getElementById(id);
function el(tag,attrs,txt){const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(txt!=null)e.textContent=txt;return e}
function pos(i,n){const a=-Math.PI/2+i*2*Math.PI/Math.max(n,1);return[200+130*Math.cos(a),200+130*Math.sin(a)]}
function teinte(r){return r>.66?"#ff4d5e":r>.33?"#ffc857":"#3dffa0"}

function rendu(s){
  const n=s.ids.length, max=Math.max(...Object.values(s.soupcons),0.01), nv=Object.keys(s.votes).length;
  const dbt=s.debat.length;
  const tours=Math.max(0,...Object.values(s.temps).map(v=>v.length));
  $("phase").textContent=!n?"en attente des capteurs…":s.fini?"partie termin\u00e9e":nv?`vote en cours (${nv}/${s.attendus||n})`:dbt?`accusations (${dbt}/${s.attendus||n})`:tours>=5&&Object.keys(s.pensees).length?"les capteurs r\u00e9fl\u00e9chissent\u2026":`mesures \u2014 tour ${tours}`;

  // radar
  const N=$("noeuds"),F=$("fleches");N.replaceChildren();F.replaceChildren();
  const P={};s.ids.forEach((id,i)=>P[id]=pos(i,n));
  for(const [v,c] of Object.entries(s.votes)){
    if(!P[v]||!P[c])continue;
    const [x1,y1]=P[v],[x2,y2]=P[c],d=Math.hypot(x2-x1,y2-y1)||1,k=30/d;
    F.append(el("line",{x1:x1+(x2-x1)*k,y1:y1+(y2-y1)*k,x2:x2-(x2-x1)*k,y2:y2-(y2-y1)*k,stroke:"#ffc857","stroke-width":2,"stroke-dasharray":"5 4","marker-end":"url(#fl)"}));
  }
  // tant que personne n'a vote : traits fins = soupcons du moment
  if(!nv)for(const d of (dbt?s.debat:Object.values(s.pensees))){
    if(!P[d.id]||!P[d.suspect])continue;
    const [x1,y1]=P[d.id],[x2,y2]=P[d.suspect],dd=Math.hypot(x2-x1,y2-y1)||1,k=30/dd;
    F.append(el("line",{x1:x1+(x2-x1)*k,y1:y1+(y2-y1)*k,x2:x2-(x2-x1)*k,y2:y2-(y2-y1)*k,stroke:"#ff4d5e","stroke-width":dbt?2:1,"stroke-dasharray":"2 5",opacity:.8}));
  }
  s.ids.forEach((id,i)=>{
    const [x,y]=P[id],t=s.temps[id]||[],r=(s.soupcons[id]||0)/max,esp=s.fini&&id===s.espion;
    const c=esp?"#ff4d5e":s.fini?"#3dffa0":teinte(tours>1?r:0);
    if(esp)N.append(el("circle",{cx:x,cy:y,r:34,fill:"none",stroke:"#ff4d5e","stroke-width":3,class:"pulse"}));
    N.append(el("circle",{cx:x,cy:y,r:24,fill:"#06110d",stroke:c,"stroke-width":3}));
    N.append(el("text",{x,y:y+5,"text-anchor":"middle",fill:c,"font-size":13},t.length?t[t.length-1].toFixed(1)+"°":"—"));
    N.append(el("text",{x,y:y+(y<200?-32:44),"text-anchor":"middle",fill:COUL[i%6],"font-size":13},esp?id+" — ESPION":id));
  });

  // courbes
  const C=$("courbes");C.replaceChildren();
  const all=Object.values(s.temps).flat();
  if(all.length){
    let lo=Math.min(...all),hi=Math.max(...all);if(hi-lo<1){lo-=.5;hi+=.5}
    const X=k=>40+k*(340/Math.max(tours-1,1)),Y=v=>150-(v-lo)/(hi-lo)*130;
    [lo,(lo+hi)/2,hi].forEach(v=>{C.append(el("line",{x1:40,x2:385,y1:Y(v),y2:Y(v),stroke:"#1d4a36"}));C.append(el("text",{x:34,y:Y(v)+4,"text-anchor":"end",fill:"#5c8f76","font-size":10},v.toFixed(1)))});
    s.ids.forEach((id,i)=>{const t=s.temps[id]||[];if(!t.length)return;
      C.append(el("polyline",{points:t.map((v,k)=>X(k)+","+Y(v)).join(" "),fill:"none",stroke:COUL[i%6],"stroke-width":2}));
      t.forEach((v,k)=>C.append(el("circle",{cx:X(k),cy:Y(v),r:3,fill:COUL[i%6]})))});
  }

  // bulles : soupcons du tour, puis accusations finales
  const U=$("bulles");U.replaceChildren();
  $("titrebulles").textContent=dbt?"ACCUSATIONS":"CE QUE PENSENT LES CAPTEURS";
  const liste=dbt?s.debat:s.ids.map(id=>s.pensees[id]).filter(Boolean);
  if(!liste.length){const v=document.createElement("div");v.className="vide";v.textContent="en attente du premier tour\u2026";U.append(v)}
  liste.forEach(d=>{const b=document.createElement("div"),h=document.createElement("b"),c=COUL[s.ids.indexOf(d.id)%6];
    b.className=dbt?"bulle acc":"bulle";b.style.borderColor=c;h.style.color=c;
    h.textContent=dbt?`${d.id} accuse ${d.suspect}`+(s.fini&&d.id===s.espion?"  (c'\u00e9tait l'espion, il mentait)":""):d.id;
    b.append(h,d.texte);U.append(b)});

  // barres de soupçon
  const B=$("barres");B.replaceChildren();
  s.ids.forEach((id,i)=>{const v=s.soupcons[id]||0,row=document.createElement("div");row.className="bar";
    const a=document.createElement("b");a.textContent=id;a.style.color=COUL[i%6];
    const w=document.createElement("div"),f=document.createElement("i");f.style.width=(v/max*100)+"%";f.style.background=teinte(v/max);w.append(f);
    const z=document.createElement("span");z.textContent=v.toFixed(2);row.append(a,w,z);B.append(row)});

  // journal
  const J=$("journal");J.replaceChildren();
  s.journal.slice().reverse().forEach(e=>{const d=document.createElement("div"),h=document.createElement("span");h.textContent=e.t;d.append(h,e.txt);J.append(d)});

  // verdict
  const V=$("verdict");
  if(s.fini){V.style.display="block";V.style.color=s.gagne?"#3dffa0":"#ff4d5e";
    V.textContent=s.gagne?`ESPION DÉMASQUÉ : ${s.espion} — LES CAPTEURS GAGNENT`:`L'ESPION ${s.espion} A GAGNÉ (désigné : ${s.designe})`}
  else V.style.display="none";
}
async function tick(){try{rendu(await (await fetch("/state")).json())}catch(e){$("phase").textContent="serveur injoignable"}}
tick();setInterval(tick,1000);
</script></body></html>"""

if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="dashboard")
    client.on_connect, client.on_message = on_connect, on_message
    client.connect(BROKER, 1883)
    client.loop_start()
    print(f"dashboard sur http://0.0.0.0:{PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
