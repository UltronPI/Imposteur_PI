import json, os, random, re, socket, statistics, time, requests
import paho.mqtt.client as mqtt

BROKER = os.getenv("BROKER", "localhost")
AGENT_URL = os.getenv("AGENT_URL", "http://localhost:5000")

def nom_agent():
    # le capteur prend le nom de son agent IA et son modèle, ex : "IMAD_Yamal_Agent (gemma3:4b)"
    try:
        d = requests.get(f"{AGENT_URL}/agent", timeout=5).json()
        nom = f"{d['name']} ({d['model']})"
    except (requests.RequestException, KeyError, ValueError):
        print("agent injoignable, j'utilise le nom de la machine")
        return socket.gethostname()
    return re.sub(r"[/+#]", "-", nom)   # caractères interdits dans un topic MQTT

ID = os.getenv("ID") or nom_agent()
LAT, LON = float(os.getenv("LAT", "45.90")), float(os.getenv("LON", "6.13"))
ROUNDS = 5

role = None   # envoyé par le serveur
hist = {}    # id -> liste des temp reçues
score = {}   # id -> écart cumulé à la médiane
mes_publiees = []   # ce que j'ai envoyé (faux si je suis l'espion)

def get_temp():
    r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=5,
        params={"latitude": LAT, "longitude": LON, "current": "temperature_2m"})
    return r.json()["current"]["temperature_2m"]

def on_connect(c, u, flags, rc, props=None):
    c.subscribe(f"iot/role/{ID}")
    c.subscribe("iot/capteurs/+/temperature")

def on_message(c, u, msg):
    global role
    if msg.topic.startswith("iot/role/"):
        role = msg.payload.decode().strip()
        print("rôle :", role)
        return
    sid = msg.topic.split("/")[2]
    if sid != ID:
        hist.setdefault(sid, []).append(float(msg.payload))
        print(f"{sid} envoie {float(msg.payload)}")

def ask_agent(cible=None):
    # mes_publiees : l'espion montre ses fausses valeurs, pas les vraies
    mesures = {**hist, ID: mes_publiees}
    r = requests.post(f"{AGENT_URL}/detect", timeout=300,
        json={"me": ID, "mesures": mesures, "role": role, "cible": cible})
    r.raise_for_status()
    d = r.json()
    return d["suspect"], d.get("raison", "")

def dire(topic, suspect, texte):
    # réflexion du capteur, affichée par le dashboard
    print(f"[{topic}] {texte}")
    client.publish(f"iot/{topic}/{ID}", json.dumps({"suspect": suspect, "texte": texte}), qos=1)

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"capteur-{ID}")
client.on_connect, client.on_message = on_connect, on_message
client.connect(BROKER, 1883)
client.loop_start()
print(f"je suis {ID}, en attente du serveur...")
while not role:
    # s'annonce jusqu'à recevoir un rôle (le serveur peut démarrer après nous)
    client.publish(f"iot/presence/{ID}", "1")
    time.sleep(2)

for i in range(ROUNDS):
    real = get_temp()
    t = real
    if role == "espion":
        t = round(real * (1 + random.choice([-1, 1]) * random.uniform(0.10, 0.20)), 1)
    mes_publiees.append(t)
    client.publish(f"iot/capteurs/{ID}/temperature", t)
    print(f"{ID} envoie {t}")
    time.sleep(5)

    if hist:
        last = {sid: v[-1] for sid, v in hist.items()}
        med = statistics.median(list(last.values()) + [real])
        for sid, v in last.items():
            score[sid] = score.get(sid, 0) + abs(v - med)
        print("scores :", {k: round(v, 2) for k, v in score.items()})
        pire = max(score, key=score.get)
        if role == "espion":
            # l'espion détourne les soupçons vers le capteur honnête le plus éloigné
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
        suspect, texte = ask_agent(cible=algo if role == "espion" else None)
        print(f"algo -> {algo} | agent -> {suspect}")
    except (requests.RequestException, KeyError, ValueError) as e:
        print("agent KO, je garde l'algo :", e)
        suspect = algo
        texte = f"J'accuse {algo} : c'est lui qui s'écarte le plus de la médiane (écart cumulé {score[algo]:.1f} °C)."
    dire("debat", suspect, texte)
    time.sleep(3)   # laisse le temps de lire l'accusation avant le vote
    client.publish(f"iot/votes/{ID}", suspect, qos=1)
    print("vote :", suspect)

time.sleep(1)
client.loop_stop()
