import os, random, sys, time
from collections import Counter
import paho.mqtt.client as mqtt

BROKER = os.getenv("BROKER", "localhost")
IDS = sys.argv[1:]
if len(IDS) < 2:
    sys.exit("usage : python serveur.py <id1> <id2> [<id3> ...]")

espion = random.choice(IDS)
votes = {}   # votant -> suspect

def on_connect(c, u, flags, rc, props=None):
    c.subscribe("iot/votes/+")
    # retain : le rôle est livré même si le capteur se connecte après
    for i in IDS:
        c.publish(f"iot/role/{i}", "espion" if i == espion else "normal", qos=1, retain=True)
    print(f"rôles envoyés à {', '.join(IDS)} (espion : {espion})")

def on_message(c, u, msg):
    votant = msg.topic.split("/")[2]
    if votant in IDS:
        votes[votant] = msg.payload.decode().strip()
        print(f"{votant} vote {votes[votant]}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="serveur")
client.on_connect, client.on_message = on_connect, on_message
client.connect(BROKER, 1883)
client.loop_start()

print("en attente des votes...")
while len(votes) < len(IDS):
    time.sleep(0.5)

compte = Counter(votes.values())
designe, nb = compte.most_common(1)[0]
print("décompte :", dict(compte))
print(f"désigné : {designe} ({nb}/{len(IDS)} votes) | vrai espion : {espion}")
if designe == espion and nb > len(IDS) / 2:
    print("les capteurs gagnent !")
else:
    print("l'espion a gagné !")

# efface les rôles retenus pour la partie suivante
for i in IDS:
    client.publish(f"iot/role/{i}", "", qos=1, retain=True)
time.sleep(1)
client.loop_stop()
