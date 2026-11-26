#!/usr/bin/env python3
import json
import os
import sys
import threading

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
from flask import Flask, jsonify, request

AGENT_NAME = "IMAD_Yamal_Agent"
Modele = os.environ.get("MODEL", "gemma3:4b")
Url_ollama = os.environ.get("OLLAMA_URL", "http://localhost:11434")
Port = int(os.environ.get("PORT", "5000"))
Timeout_llm = 300

app = Flask(__name__)
app.json.ensure_ascii = False

llm_lock = threading.Lock()


@app.get("/health")
def health():
    try:
        r = requests.get(f"{Url_ollama}/api/tags", timeout=5)
        r.raise_for_status()
        ollama = "ok"
    except requests.RequestException:
        ollama = "injoignable"

    status = "ok" if ollama == "ok" else "degraded"
    code = 200 if status == "ok" else 503
    return jsonify(status=status, agent=AGENT_NAME, ollama=ollama), code


@app.get("/agent")
def agent():
    return jsonify(
        name=AGENT_NAME,
        model=Modele,
        description="Agent du jeu Chasse à Ultron sur Raspberry Pi, propulsé par Ollama",
        capabilities=[
            "Analyser les températures et désigner le capteur suspect",
        ],
        routes={
            "GET /health": "vérifier si l'agent et Ollama sont vivants",
            "GET /agent": "découvrir ce que l'agent sait faire",
            "POST /detect": '{"me": "id", "mesures": {"id": [..]}, "role": "normal|ultron"}',
        },
    )


Prompt_detect = (
    "Tu es un capteur de température dans un jeu de détection d'Ultron. "
    "Chaque capteur mesure la température d'une ville voisine, donc les valeurs honnêtes sont proches. "
    "Un seul capteur est Ultron, un imposteur qui envoie des valeurs fausses, environ 10 à 20 % différentes des autres. "
    "Analyse les mesures et désigne le capteur le plus suspect. Tu ne peux pas te désigner toi-même."
)
Prompt_mentir = (
    "Tu es un capteur de température dans un jeu de détection d'Ultron, et Ultron c'est toi. "
    "Personne ne doit le savoir. Choisis parmi les autres capteurs celui qu'il est le plus crédible "
    "d'accuser à ta place, par exemple celui dont les valeurs s'écartent le plus du reste. "
    "Invente un argument crédible contre lui à partir des mesures, et ne dis jamais que tu es Ultron."
)
Prompt_style = (
    " Tu es le capteur {me}. Dans 'raison', écris l'accusation que tu lances devant les autres : "
    "commence par 'J'accuse <suspect>', puis donne en une phrase ses valeurs qui posent problème. "
    "Tu ne peux pas t'accuser toi-même ({me}). En français, 2 phrases maximum."
)


@app.post("/detect")
def detect():
    data = request.get_json(silent=True) or {}
    me = str(data.get("me", ""))
    mesures = data.get("mesures") or {}
    candidats = [sid for sid in mesures if sid != me]
    if not candidats:
        return jsonify(error="Aucune mesure d'autres capteurs"), 400

    lignes = "\n".join(
        f"- capteur {sid}{' (moi)' if sid == me else ''} : {', '.join(map(str, vals))}"
        for sid, vals in mesures.items())
    system = Prompt_detect + Prompt_style.format(me=me)
    if data.get("role") == "ultron":
        system = Prompt_mentir + Prompt_style.format(me=me)
    payload = {
        "model": Modele,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Mesures en °C sur les derniers tours :\n{lignes}\nQui est Ultron ?"},
        ],
        "stream": False,
        "think": False,
        "format": {
            "type": "object",
            "properties": {
                "suspect": {"type": "string", "enum": candidats},
                "raison": {"type": "string"},
            },
            "required": ["suspect", "raison"],
        },
        "options": {"temperature": 0},
    }
    with llm_lock:
        try:
            r = requests.post(f"{Url_ollama}/api/chat", json=payload, timeout=Timeout_llm)
            r.raise_for_status()
            result = json.loads(r.json()["message"]["content"])
        except (requests.RequestException, ValueError, KeyError) as e:
            return jsonify(error=f"Ollama ne répond pas : {e}"), 502

    print(f"[detect]\n{lignes}\n-> {result}", flush=True)
    return jsonify(agent=AGENT_NAME, **result)


if __name__ == "__main__":
    print(f"Agent {AGENT_NAME} (modèle {Modele}) sur le port {Port}", flush=True)
    app.run(host="0.0.0.0", port=Port, threaded=True)
