# Chasse à l'espion — jeu distribué MQTT

TP R5.A.05 (IUT d'Annecy). Quatre Raspberry Pi jouent le rôle de capteurs de température et s'échangent des mesures via MQTT. L'un d'eux est un espion qui envoie de fausses valeurs : les autres doivent le démasquer par un vote.

## Règles

- Le serveur tire un espion au hasard et envoie son rôle à chaque Pi.
- Toutes les 5 secondes, chaque Pi publie la température de sa ville (API Open-Meteo). L'espion publie une valeur faussée.
- Après 5 échanges, chaque Pi vote pour le capteur qu'il soupçonne.
- Si la majorité désigne l'espion, les capteurs gagnent. Sinon, l'espion gagne.

## Fichiers

| Fichier | Rôle |
|---|---|
| `serveur.py` | Attribue les rôles, compte les votes, annonce le résultat |
| `capteur.py` | Publie les températures, détecte l'espion, vote |
| `dashboard.py` | Tableau de bord web : radar des capteurs, courbes, votes, verdict |
| `agent.py` | Extension : agent LLM (Ollama) qui donne son avis sur l'espion |

## Topics MQTT

| Topic | Contenu |
|---|---|
| `iot/role/<id>` | Rôle envoyé par le serveur (`normal` ou `espion`) |
| `iot/capteurs/<id>/temperature` | Température publiée par un capteur |
| `iot/votes/<id>` | Vote d'un capteur |
| `iot/raison/<id>` | Explication donnée par l'agent LLM (pour le tableau de bord) |

## Installation

Sur chaque Pi :

```bash
pip install paho-mqtt requests
```

Sur le Pi qui héberge le jeu, il faut en plus le broker Mosquitto et Flask :

```bash
sudo apt install mosquitto
pip install flask
```

Le broker doit accepter les connexions du réseau (`/etc/mosquitto/conf.d/tp.conf`) :

```
listener 1883
allow_anonymous true
```

## Lancer une partie

Sur le Pi hôte, dans cet ordre :

```bash
python3 dashboard.py                  # puis ouvrir http://<ip-du-pi>:8080
python3 serveur.py pi1 pi2 pi3 pi4
```

Sur chaque Pi capteur, avec son identifiant et sa ville :

```bash
ID=pi2 LAT=45.92 LON=6.87 BROKER=<ip-du-pi-hote> python3 capteur.py
```

| ID | Ville | LAT | LON |
|---|---|---|---|
| pi1 | Annecy | 45.90 | 6.13 |
| pi2 | Chamonix | 45.92 | 6.87 |
| pi3 | Aix-les-Bains | 45.69 | 5.91 |
| pi4 | Genève | 46.19 | 6.23 |

Les identifiants doivent être ceux passés au serveur.

## Détection de l'espion

Chaque capteur compare, à chaque tour, les valeurs reçues à la médiane et cumule l'écart de chaque voisin. Le capteur avec le plus grand écart cumulé est le suspect.

## Extension : agent LLM

Chaque Pi exécute Ollama (modèle `gemma3:4b`) et `agent.py`, qui expose une route `POST /detect`. Le capteur lui envoie toutes les mesures et vote en suivant son avis. Si l'agent ne répond pas, le capteur garde le résultat de l'algorithme.

```bash
ollama pull gemma3:4b
python3 agent.py                      # écoute sur le port 5000
```

Variables d'environnement du capteur : `ID`, `BROKER`, `AGENT_URL`, `LAT`, `LON`.
