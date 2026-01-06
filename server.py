# server.py
# -------------------------------------------------------------------------
# SERVEUR WIKIMIND SHARED (Bêta)
# Gère les WebSockets et l'intelligence artificielle côté serveur.
# -------------------------------------------------------------------------

import json
import random
import string
import os
import requests
from typing import List, Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

# Configuration CORS pour autoriser le frontend GitHub Pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En prod, remplacer par l'URL GitHub Pages
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CLÉ API (À configurer ici ou via variable d'environnement)
# Utilise la même clé Groq que le frontend pour la cohérence
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")
AI_MODEL = "llama-3.3-70b-versatile"

# --- GESTION DES ROOMS ---

class ConnectionManager:
    def __init__(self):
        # Map: room_code -> List[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # Map: room_code -> List[Dict] (Historique pour le contexte IA)
        self.chat_histories: Dict[str, List[Dict]] = {}

    async def connect(self, websocket: WebSocket, room_code: str):
        await websocket.accept()
        if room_code not in self.active_connections:
            self.active_connections[room_code] = []
            self.chat_histories[room_code] = []
        self.active_connections[room_code].append(websocket)

    def disconnect(self, websocket: WebSocket, room_code: str):
        if room_code in self.active_connections:
            self.active_connections[room_code].remove(websocket)
            if not self.active_connections[room_code]:
                del self.active_connections[room_code]
                # On garde l'historique un peu en mémoire ou on le supprime
                # del self.chat_histories[room_code]

    async def broadcast(self, message: dict, room_code: str):
        # Sauvegarde dans l'historique
        if room_code not in self.chat_histories:
            self.chat_histories[room_code] = []
        
        # On ne garde que les 20 derniers messages pour le contexte
        self.chat_histories[room_code].append(message)
        if len(self.chat_histories[room_code]) > 20:
            self.chat_histories[room_code].pop(0)

        # Envoi à tous les clients connectés
        if room_code in self.active_connections:
            for connection in self.active_connections[room_code]:
                await connection.send_text(json.dumps(message))

    def get_history(self, room_code: str):
        return self.chat_histories.get(room_code, [])

manager = ConnectionManager()

# --- LOGIQUE IA ---

def ask_ai(context_messages: List[Dict], user_query: str):
    """Appelle l'API Groq côté serveur"""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Construction du prompt système
    system_prompt = {
        "role": "system",
        "content": (
            "Tu es WikiMind, un assistant IA dans une conversation de groupe. "
            "Tu interviens uniquement quand on t'appelle. "
            "Sois concis, utile et amical. Tu vois l'historique de la conversation."
        )
    }

    # Formatage de l'historique pour l'API
    messages = [system_prompt]
    for msg in context_messages:
        role = "assistant" if msg.get("is_ai") else "user"
        content = f"{msg.get('author', 'User')}: {msg.get('content', '')}"
        messages.append({"role": role, "content": content})

    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "temperature": 0.7
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Erreur IA: {e}")
        return "Désolé, je rencontre un problème technique momentané."

# --- ENDPOINTS ---

@app.websocket("/ws/{room_code}/{username}")
async def websocket_endpoint(websocket: WebSocket, room_code: str, username: str):
    await manager.connect(websocket, room_code)
    
    # Notification de connexion
    await manager.broadcast({
        "type": "system",
        "content": f"🔵 {username} a rejoint la conversation."
    }, room_code)

    try:
        while True:
            data = await websocket.receive_text()
            # Le client envoie juste le contenu texte
            
            # 1. Diffuser le message utilisateur
            user_msg_obj = {
                "type": "message",
                "author": username,
                "content": data,
                "is_ai": False,
                "timestamp": "Now" 
            }
            await manager.broadcast(user_msg_obj, room_code)

            # 2. Détection du trigger IA
            if "@wikimind" in data.lower():
                # Notification visuelle que l'IA réfléchit
                await manager.broadcast({
                    "type": "typing",
                    "content": "WikiMind écrit..."
                }, room_code)

                # Appel synchrone (bloquant simple pour cet exemple) ou asynchrone
                history = manager.get_history(room_code)
                ai_response = ask_ai(history, data)

                # Diffusion réponse IA
                ai_msg_obj = {
                    "type": "message",
                    "author": "WikiMind",
                    "content": ai_response,
                    "is_ai": True,
                    "timestamp": "Now"
                }
                await manager.broadcast(ai_msg_obj, room_code)

    except WebSocketDisconnect:
        manager.disconnect(websocket, room_code)
        await manager.broadcast({
            "type": "system",
            "content": f"🔴 {username} a quitté la conversation."
        }, room_code)

if __name__ == "__main__":
    # Lancer avec: python server.py
    uvicorn.run(app, host="0.0.0.0", port=8000)
