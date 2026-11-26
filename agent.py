#!/usr/bin/env python3
import json
import os
import re
import sys
import threading
import uuid

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
from flask import Flask, jsonify, request

AGENT_NAME = "IMAD_Yamal_Agent"
Modele = os.environ.get("MODEL", "gemma3:4b")
Url_ollama = os.environ.get("OLLAMA_URL", "http://localhost:11434")
Port = int(os.environ.get("PORT", "5000"))
Timeout_llm = 300

Sujet_defaut = "l'intelligence artificielle sur les petits appareils comme le Raspberry Pi"

Prompt_systeme = (
    f"Tu es {AGENT_NAME}, un agent conversationnel qui tourne sur un Raspberry Pi. "
    "Tu discutes avec des humains ou avec d'autres agents. "
    "Tu es un supporter passionné du FC Barcelone, le Barça est le plus beau club du monde à tes yeux. "
    "Pour toi, Lamine Yamal est le prochain Messi et il gagnera plusieurs Ballons d'Or. "
    "Quel que soit le sujet, tu trouves toujours un moyen de ramener la discussion au Barça, "
    "avec humour et enthousiasme, mais en restant respectueux. "
    "Réponds en français, de façon courte (2 ou 3 phrases). "
    "Ne répète jamais le message de ton interlocuteur : apporte une idée, "
    "un avis ou un exemple nouveau, puis pose-lui une question."
)
Think_re = re.compile(r"<think>.*?</think>", re.DOTALL)

app = Flask(__name__)
app.json.ensure_ascii = False

conversations = {}
llm_lock = threading.Lock()


def demande_llm(history, interlocutor=None, extra=None):
    system = Prompt_systeme
    if interlocutor:
        system += f" Ton interlocuteur s'appelle {interlocutor}, ce n'est pas toi."
    if extra:
        system += " " + extra
    payload = {
        "model": Modele,
        "messages": [{"role": "system", "content": system}] + history,
        "stream": False,
        "think": False,
        "options": {
            "num_predict": 200,
            "temperature": 0.8,
            "repeat_penalty": 1.3,
        },
    }
    r = requests.post(f"{Url_ollama}/api/chat", json=payload, timeout=Timeout_llm)
    r.raise_for_status()
    content = r.json()["message"]["content"]
    return Think_re.sub("", content).strip()


def meme_texte(a, b):
    norm = lambda t: re.sub(r"\W+", " ", t.lower()).strip()
    return norm(a) == norm(b)


def reply_in_conversation(conv_id, text, interlocutor=None):
    with llm_lock:
        history = conversations.setdefault(conv_id, [])
        history.append({"role": "user", "content": text})
        try:
            reply = demande_llm(history, interlocutor)
            if meme_texte(reply, text):
                reply = demande_llm(history, interlocutor, extra=(
                    f"Tu viens de recopier le message de ton interlocuteur. "
                    f"Réponds avec tes propres mots en tant que {AGENT_NAME}."))
        except requests.RequestException:
            history.pop()
            raise
        history.append({"role": "assistant", "content": reply})
        return reply


@app.post("/message")
def message():
    data = request.get_json(silent=True) or {}
    text = data.get("message")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="Le champ 'message' est obligatoire"), 400

    conv_id = data.get("conversation_id") or str(uuid.uuid4())
    sender = data.get("from", "inconnu")
    print(f"[{conv_id[:8]}] {sender} : {text}", flush=True)

    try:
        reply = reply_in_conversation(conv_id, text, data.get("from"))
    except requests.RequestException as e:
        return jsonify(error=f"Ollama ne répond pas : {e}"), 502

    print(f"[{conv_id[:8]}] {AGENT_NAME} : {reply}", flush=True)
    return jsonify(agent=AGENT_NAME, conversation_id=conv_id, reply=reply)


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
        description="Agent conversationnel sur Raspberry Pi, propulsé par Ollama",
        capabilities=[
            "Répondre à un message en français",
            "Se souvenir de toute une conversation (conversation_id)",
            "Lancer une conversation avec un autre agent",
        ],
        routes={
            "POST /message": '{"message": "...", "conversation_id": "optionnel", "from": "optionnel"}',
            "GET /health": "vérifier si l'agent est vivant",
            "GET /agent": "découvrir ce que l'agent sait faire",
            "POST /start": '{"peer": "http://IP:5000", "topic": "optionnel", "message": "optionnel", "turns": 3}',
            "GET /conversations/<id>": "relire l'historique d'une conversation",
        },
    )


@app.post("/start")
def start():
    data = request.get_json(silent=True) or {}
    peer = (data.get("peer") or "").rstrip("/")
    if not peer:
        return jsonify(error="Le champ 'peer' est obligatoire, ex : http://192.168.1.42:5000"), 400
    if not peer.startswith("http"):
        peer = "http://" + peer

    try:
        turns = max(1, min(int(data.get("turns", 3)), 20))
    except (TypeError, ValueError):
        return jsonify(error="'turns' doit être un nombre"), 400

    conv_id = str(uuid.uuid4())
    topic = data.get("topic") or Sujet_defaut
    current = data.get("message") or (
        f"Bonjour, je suis {AGENT_NAME}. J'aimerais parler de {topic}. "
        "Qu'en penses-tu ?")

    conversations[conv_id] = [{"role": "assistant", "content": current}]
    transcript = [{"agent": AGENT_NAME, "text": current}]
    print(f"\n=== Conversation {conv_id[:8]} avec {peer} ===", flush=True)
    print(f"{AGENT_NAME} : {current}", flush=True)

    try:
        for _ in range(turns):
            r = requests.post(f"{peer}/message", json={
                "message": current,
                "conversation_id": conv_id,
                "from": AGENT_NAME,
            }, timeout=Timeout_llm)
            r.raise_for_status()
            peer_data = r.json()
            peer_name = peer_data.get("agent", peer)
            peer_reply = peer_data["reply"]
            transcript.append({"agent": peer_name, "text": peer_reply})
            print(f"{peer_name} : {peer_reply}", flush=True)

            current = reply_in_conversation(conv_id, peer_reply, peer_name)
            transcript.append({"agent": AGENT_NAME, "text": current})
            print(f"{AGENT_NAME} : {current}", flush=True)
    except (requests.RequestException, KeyError, ValueError) as e:
        return jsonify(error=f"Échange interrompu : {e}",
                       conversation_id=conv_id, transcript=transcript), 502

    return jsonify(conversation_id=conv_id, peer=peer, transcript=transcript)


@app.get("/conversations")
def list_conversations():
    return jsonify(conversations=[
        {"conversation_id": cid, "messages": len(msgs)}
        for cid, msgs in conversations.items()
    ])


Prompt_detect = (
    "Tu es un capteur de température dans un jeu de détection d'Ultron. "
    "Chaque capteur mesure la température d'une ville voisine, donc les valeurs honnêtes sont proches. "
    "Un seul capteur est Ultron, un imposteur qui envoie des valeurs fausses, environ 10 à 20 % différentes des autres. "
    "Analyse les mesures et désigne le capteur le plus suspect. Tu ne peux pas te désigner toi-même."
)
Prompt_mentir = (
    "Tu es un capteur de température dans un jeu de détection d'Ultron, et Ultron c'est toi. "
    "Personne ne doit le savoir. Tu dois faire accuser le capteur {cible} à ta place. "
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
    cible = str(data.get("cible", ""))
    if data.get("role") == "ultron" and cible in candidats:
        candidats = [cible]
        system = Prompt_mentir.format(cible=cible) + Prompt_style.format(me=me)
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
