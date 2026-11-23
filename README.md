# Chasse à l'espion — jeu distribué MQTT

TP R5.A.05 (IUT d'Annecy). Plusieurs Raspberry Pi jouent le rôle de capteurs de température et s'échangent des mesures via MQTT. L'un d'eux est un espion qui envoie de fausses valeurs : les autres doivent le démasquer par un vote.

## Règles

- Le serveur tire un espion au hasard et envoie son rôle à chaque Pi.
- Toutes les 5 secondes, chaque Pi publie la température de sa ville (API Open-Meteo). L'espion publie une valeur faussée de 10 à 20 %.
- Après 5 échanges, chaque Pi vote pour le capteur qu'il soupçonne.
- Si la majorité désigne l'espion, les capteurs gagnent. Sinon, l'espion gagne.

## Fichiers

| Fichier | Où | Rôle |
|---|---|---|
| `serveur.py` | hôte | Attribue les rôles, compte les votes, annonce le résultat |
| `dashboard.py` | hôte | Tableau de bord web : radar des capteurs, courbes, votes, verdict |
| `capteur.py` | tous | Publie les températures, détecte l'espion, vote |
| `agent.py` | tous | Agent LLM (Ollama) qui donne son avis sur l'espion |

## Réseau

L'hôte est toujours le Pi **`10.109.150.44`**. Il fait tourner le broker Mosquitto, le serveur et le dashboard.

Dashboard : **http://10.109.150.44:8080**

## Installation (une seule fois)

### Sur tous les Pi

```bash
git clone https://github.com/imademo-png/projet_imposteur.git
cd projet_imposteur
pip install paho-mqtt requests flask
ollama pull gemma3:4b
```

Chaque joueur doit donner **un nom unique** à son agent dans `agent.py` :

```python
AGENT_NAME = "Mon_Agent"
```

Le capteur prend ce nom pour jouer. Si deux agents portent le même nom, le serveur ne voit qu'un seul joueur et le broker déconnecte l'un des deux.

### En plus sur l'hôte

```bash
sudo apt install mosquitto
```

Le broker doit accepter les connexions du réseau. Il faut créer `/etc/mosquitto/conf.d/tp.conf` :

```
listener 1883
allow_anonymous true
```

puis lancer `sudo systemctl restart mosquitto`.

## Lancer une partie

Avant chaque partie, tout le monde récupère la dernière version :

```bash
git pull
```

### Sur l'hôte (10.109.150.44)

Il faut un terminal par commande :

```bash
python3 dashboard.py                      # 1. tableau de bord sur :8080
python3 agent.py                          # 2. attendre "Running on http://..."
LAT=45.90 LON=6.13 python3 capteur.py     # 3. l'hôte joue aussi (broker en local)
python3 serveur.py <nb_joueurs>           # 4. ex : 2 si vous êtes deux, hôte compris
```

### Sur les autres Pi

Il faut un terminal par commande :

```bash
python3 agent.py                          # 1. attendre "Running on http://..."
BROKER=10.109.150.44 LAT=45.92 LON=6.87 python3 capteur.py   # 2. avec sa ville
```

> ⚠️ Il faut lancer le capteur **après** que l'agent affiche « Running on ». Sinon le capteur ne trouve pas l'agent et s'appelle `raspberrypi-<fin de l'IP>`, puis il joue sans IA.

Les capteurs s'annoncent toutes les 2 secondes. Ils peuvent donc démarrer avant ou après le serveur. Le serveur envoie les rôles dès que `<nb_joueurs>` capteurs se sont annoncés.

### Villes

| Ville | LAT | LON |
|---|---|---|
| Annecy | 45.90 | 6.13 |
| Chamonix | 45.92 | 6.87 |
| Aix-les-Bains | 45.69 | 5.91 |
| Genève | 46.19 | 6.23 |

### Relancer une partie

Il faut couper le serveur et tous les capteurs (Ctrl+C), puis relancer le serveur et les capteurs. Les agents et le dashboard peuvent continuer à tourner. Si le serveur reste lancé, il garde en mémoire les joueurs déjà inscrits.

## Topics MQTT

| Topic | Contenu |
|---|---|
| `iot/presence/<id>` | Un capteur s'annonce au serveur |
| `iot/role/<id>` | Rôle envoyé par le serveur (`normal` ou `espion`) |
| `iot/capteurs/<id>/temperature` | Température publiée par un capteur |
| `iot/soupcon/<id>` | Soupçon d'un capteur à chaque tour (JSON `suspect`, `texte`) |
| `iot/debat/<id>` | Accusation finale donnée par l'agent (JSON `suspect`, `texte`) |
| `iot/votes/<id>` | Vote d'un capteur |

## Détection de l'espion

À chaque tour, chaque capteur compare les valeurs reçues à la médiane et cumule l'écart de chaque voisin. Le capteur qui a le plus grand écart cumulé est le suspect.

À la fin, le capteur envoie toutes les mesures à son agent (`POST /detect`) et vote en suivant son avis. Si l'agent ne répond pas, le capteur garde le résultat de l'algorithme.

## Options

| Variable | Script | Défaut | Rôle |
|---|---|---|---|
| `BROKER` | capteur, serveur, dashboard | `localhost` | IP du broker (`10.109.150.44` sur les autres Pi) |
| `LAT`, `LON` | capteur | Annecy | Ville du capteur |
| `ID` | capteur | nom de l'agent | Force le nom du capteur |
| `AGENT_URL` | capteur | `http://localhost:5000` | Adresse de l'agent |
| `MODEL` | agent | `gemma3:4b` | Modèle Ollama |
| `PORT` | agent, dashboard | `5000`, `8080` | Port d'écoute |
| `VOTE_TIMEOUT` | serveur | `420` | Attente maximale des votes (s) |

`python3 serveur.py pi1 pi2 ...` attend ces capteurs précis au lieu d'un nombre de joueurs.
