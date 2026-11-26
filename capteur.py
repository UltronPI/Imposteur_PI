import json, os, random, re, socket, statistics, time, requests
import paho.mqtt.client as mqtt

Brok = os.getenv("BROKER", "localhost")
Url_agent = os.getenv("AGENT_URL", "http://localhost:5000")

def mon_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8" if Brok == "localhost" else Brok, 1883))
        return s.getsockname()[0]
    except OSError:
        return str(random.randint(100, 999))
    finally:
        s.close()

def nom_agent():
    try:
        d = requests.get(f"{Url_agent}/agent", timeout=5).json()
        nom = f"{d['name']} ({d['model']})"
    except (requests.RequestException, KeyError, ValueError):
        nom = f"{socket.gethostname()}-{mon_ip().split('.')[-1]}"
        print(f"agent injoignable sur {Url_agent}, j'utilise le nom {nom}")
        return nom
    return re.sub(r"[/+#]", "-", nom)

Id = os.getenv("ID") or nom_agent()
Lat, Lon = float(os.getenv("LAT", "45.90")), float(os.getenv("LON", "6.13"))
Nb_tours = 5

role = None
hist = {}
score = {}
debats = {}
mes_publiees = []

def get_temp():
    try:
        return _get_temp()
    except (requests.RequestException, KeyError, ValueError) as e:
        print("météo injoignable, je réutilise ma dernière valeur :", e)
        return mes_publiees[-1] if mes_publiees else 10.0

def _get_temp():
    r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=5,
        params={"latitude": Lat, "longitude": Lon, "current": "temperature_2m"})
    return r.json()["current"]["temperature_2m"]

def on_connect(c, u, flags, rc, props=None):
    c.subscribe(f"iot/role/{Id}")
    c.subscribe("iot/capteurs/+/temperature")
    c.subscribe("iot/debat/+")

def on_message(c, u, msg):
    global role
    if msg.topic.startswith("iot/role/"):
        if msg.retain:
            return
        role = msg.payload.decode().strip()
        print("rôle :", role)
        return
    sid = msg.topic.split("/")[2]
    if msg.topic.startswith("iot/debat/"):
        if sid != Id and sid not in debats:
            try:
                debats[sid] = str(json.loads(msg.payload)["texte"])
            except (ValueError, KeyError, TypeError):
                pass
        return
    if sid != Id:
        hist.setdefault(sid, []).append(float(msg.payload))
        print(f"{sid} envoie {float(msg.payload)}")

def ask_agent(debat=None):
    mesures = {**hist, Id: mes_publiees}
    r = requests.post(f"{Url_agent}/detect", timeout=300,
        json={"me": Id, "mesures": mesures, "role": role, "debat": debat or {}})
    r.raise_for_status()
    d = r.json()
    return d["suspect"], d.get("raison", "")

def dire(topic, suspect, texte):
    print(f"[{topic}] {texte}")
    client.publish(f"iot/{topic}/{Id}", json.dumps({"suspect": suspect, "texte": texte}), qos=1)

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"capteur-{Id}")
client.on_connect, client.on_message = on_connect, on_message
client.connect(Brok, 1883)
client.loop_start()
print(f"je suis {Id}, en attente du serveur...")
while not role:
    client.publish(f"iot/presence/{Id}", "1")
    time.sleep(2)

for i in range(Nb_tours):
    real = get_temp()
    t = real
    if role == "ultron":
        t = round(real * (1 + random.choice([-1, 1]) * random.uniform(0.10, 0.20)), 1)
    mes_publiees.append(t)
    client.publish(f"iot/capteurs/{Id}/temperature", t)
    print(f"{Id} envoie {t}")
    time.sleep(5)

    if hist:
        last = {sid: v[-1] for sid, v in hist.items()}
        med = statistics.median(list(last.values()) + [real])
        for sid, v in last.items():
            score[sid] = score.get(sid, 0) + abs(v - med)
        print("scores :", {k: round(v, 2) for k, v in score.items()})
        pire = max(score, key=score.get)
        if role == "ultron":
            dire("soupcon", pire, f"Tour {i+1} : {pire} m'inquiète, il a envoyé {last[pire]} °C.")
        elif score[pire] < 0.5:
            dire("soupcon", None, f"Tour {i+1} : rien de suspect, tout le monde est proche de {med:.1f} °C.")
        else:
            dire("soupcon", pire, f"Tour {i+1} : je soupçonne {pire}, il annonce {last[pire]} °C "
                 f"alors que la médiane est à {med:.1f} °C (écart cumulé {score[pire]:.1f}).")

if score:
    algo = max(score, key=score.get)
    print("l'agent réfléchit...")
    try:
        suspect, texte = ask_agent()
        print(f"algo -> {algo} | agent -> {suspect}")
    except (requests.RequestException, KeyError, ValueError) as e:
        print("agent KO, je garde l'algo :", e)
        suspect = algo
        texte = f"J'accuse {algo} : c'est lui qui s'écarte le plus de la médiane (écart cumulé {score[algo]:.1f} °C)."
    dire("debat", suspect, texte)

    print("j'écoute les accusations des autres...")
    fin = time.time() + 120
    while len(debats) < len(hist) and time.time() < fin:
        time.sleep(0.5)
    if debats:
        try:
            vote, texte = ask_agent(debat=debats)
            print(f"avant débat -> {suspect} | après débat -> {vote}")
            suspect = vote
            dire("debat", suspect, texte)
        except (requests.RequestException, KeyError, ValueError) as e:
            print("agent KO pour le vote, je garde mon accusation :", e)
    time.sleep(3)
    client.publish(f"iot/votes/{Id}", suspect, qos=1)
    print("vote :", suspect)
else:
    print("aucune mesure reçue des autres capteurs (même BROKER ?), vote blanc")
    client.publish(f"iot/votes/{Id}", "blanc", qos=1)

time.sleep(1)
client.loop_stop()
