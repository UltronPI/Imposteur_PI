import os, random, sys, time
from collections import Counter
import paho.mqtt.client as mqtt

Brok = os.getenv("BROKER", "localhost")
Args = sys.argv[1:]
if len(Args) == 1 and Args[0].isdigit():
    Nb, Liste = int(Args[0]), []
else:
    Nb, Liste = len(Args), Args
Ids = []
if Nb < 2:
    sys.exit("usage : python serveur.py <nb_joueurs>  ou  python serveur.py <id1> <id2> [...]")

votes = {}

def on_connect(c, u, flags, rc, props=None):
    c.subscribe("iot/votes/+")
    c.subscribe("iot/presence/+")

def on_message(c, u, msg):
    if msg.topic.startswith("iot/presence/"):
        sid = msg.topic.split("/")[2]
        if len(Ids) < Nb and sid not in Ids and (not Liste or sid in Liste):
            Ids.append(sid)
            print(f"{sid} rejoint la partie ({len(Ids)}/{Nb})")
        return
    votant = msg.topic.split("/")[2]
    if votant in Ids:
        votes[votant] = msg.payload.decode().strip()
        print(f"{votant} vote {votes[votant]}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="serveur")
client.on_connect, client.on_message = on_connect, on_message
client.connect(Brok, 1883)
client.loop_start()

if len(Ids) < Nb:
    print(f"en attente de {Nb} capteurs...")
while len(Ids) < Nb:
    time.sleep(0.5)

ultron = random.choice(Ids)
for i in Ids:
    client.publish(f"iot/role/{i}", "ultron" if i == ultron else "normal", qos=1)
print(f"rôles envoyés à {', '.join(Ids)} (Ultron : {ultron})")

Timeout_vote = float(os.getenv("VOTE_TIMEOUT", "420"))
print("en attente des votes...")
fin = time.time() + Timeout_vote
while len(votes) < len(Ids) and time.time() < fin:
    time.sleep(0.5)
absents = [i for i in Ids if i not in votes]
if absents:
    print("pas de vote de :", ", ".join(absents))
if not votes:
    sys.exit("aucun vote reçu, partie annulée")

compte = Counter(votes.values())
designe, nb = compte.most_common(1)[0]
print("décompte :", dict(compte))
print(f"désigné : {designe} ({nb}/{len(Ids)} votes) | vrai Ultron : {ultron}")
if designe == ultron and nb > len(Ids) / 2:
    print("les capteurs gagnent !")
else:
    print("Ultron a gagné !")

time.sleep(1)
client.loop_stop()
