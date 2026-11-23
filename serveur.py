import os, random, sys, time
from collections import Counter
import paho.mqtt.client as mqtt

BROKER = os.getenv("BROKER", "localhost")
# soit un nombre de joueurs (les capteurs s'annoncent avec le nom de leur agent),
# soit la liste des identifiants
ARGS = sys.argv[1:]
if len(ARGS) == 1 and ARGS[0].isdigit():
    NB, LISTE = int(ARGS[0]), []
else:
    NB, LISTE = len(ARGS), ARGS
IDS = []     # capteurs qui se sont annoncés
if NB < 2:
    sys.exit("usage : python serveur.py <nb_joueurs>  ou  python serveur.py <id1> <id2> [...]")

votes = {}   # votant -> suspect

def on_connect(c, u, flags, rc, props=None):
    c.subscribe("iot/votes/+")
    c.subscribe("iot/presence/+")

def on_message(c, u, msg):
    if msg.topic.startswith("iot/presence/"):
        sid = msg.topic.split("/")[2]
        if len(IDS) < NB and sid not in IDS and (not LISTE or sid in LISTE):
            IDS.append(sid)
            print(f"{sid} rejoint la partie ({len(IDS)}/{NB})")
        return
    votant = msg.topic.split("/")[2]
    if votant in IDS:
        votes[votant] = msg.payload.decode().strip()
        print(f"{votant} vote {votes[votant]}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="serveur")
client.on_connect, client.on_message = on_connect, on_message
client.connect(BROKER, 1883)
client.loop_start()

if len(IDS) < NB:
    print(f"en attente de {NB} capteurs...")
while len(IDS) < NB:
    time.sleep(0.5)

espion = random.choice(IDS)
# pas de retain : les capteurs sont connectés puisqu'ils viennent de s'annoncer
for i in IDS:
    client.publish(f"iot/role/{i}", "espion" if i == espion else "normal", qos=1)
print(f"rôles envoyés à {', '.join(IDS)} (espion : {espion})")

# les agents peuvent mettre jusqu'à 5 min à répondre
VOTE_TIMEOUT = float(os.getenv("VOTE_TIMEOUT", "420"))
print("en attente des votes...")
fin = time.time() + VOTE_TIMEOUT
while len(votes) < len(IDS) and time.time() < fin:
    time.sleep(0.5)
absents = [i for i in IDS if i not in votes]
if absents:
    print("pas de vote de :", ", ".join(absents))
if not votes:
    sys.exit("aucun vote reçu, partie annulée")

compte = Counter(votes.values())
designe, nb = compte.most_common(1)[0]
print("décompte :", dict(compte))
print(f"désigné : {designe} ({nb}/{len(IDS)} votes) | vrai espion : {espion}")
if designe == espion and nb > len(IDS) / 2:
    print("les capteurs gagnent !")
else:
    print("l'espion a gagné !")

time.sleep(1)
client.loop_stop()
