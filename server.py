import os
import json
import requests
from typing import List, Dict
from collections import defaultdict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# --- CONFIGURATION ---
app = FastAPI()

# Clé API GROQ (À renseigner ou récupérer depuis les variables d'environnement)
# J'utilise une des clés publiques présentes dans votre code JS pour que cela fonctionne "out of the box"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")

# Configuration CORS pour autoriser le frontend (GitHub Pages ou Localhost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À restreindre en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- GESTION DES ROOMS ---
class ConnectionManager:
    def __init__(self):
        # Stocke les connexions actives : rooms[room_id] = [WebSocket, ...]
        self.active_connections: Dict[str, List[WebSocket]] = defaultdict(list)
        # Stocke un historique léger pour le contexte IA : histories[room_id] = [{"role": "user", "content": "msg"}, ...]
        self.room_histories: Dict[str, List[dict]] = defaultdict(list)

    async def connect(self, websocket: WebSocket, room_id: str):
        await websocket.accept()
        self.active_connections[room_id].append(websocket)

    def disconnect(self, websocket: WebSocket, room_id: str):
        if room_id in self.active_connections:
            if websocket in self.active_connections[room_id]:
                self.active_connections[room_id].remove(websocket)
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]
                # On pourrait aussi nettoyer l'historique ici

    async def broadcast(self, message: dict, room_id: str):
        # Sauvegarde dans l'historique (limité aux 20 derniers messages)
        self.room_histories[room_id].append({"role": "user" if not message.get("is_ai") else "assistant", "content": message["content"]})
        if len(self.room_histories[room_id]) > 20:
            self.room_histories[room_id].pop(0)

        # Envoi à tous les clients connectés
        to_remove = []
        if room_id in self.active_connections:
            for connection in self.active_connections[room_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    to_remove.append(connection)
            
            for dead_conn in to_remove:
                self.disconnect(dead_conn, room_id)

    def get_history(self, room_id: str):
        return self.room_histories[room_id]

manager = ConnectionManager()

# --- INTELLIGENCE ARTIFICIELLE ---
def ask_wikimind_ai(context_history: List[dict], user_prompt: str):
    """
    Appelle l'API Groq pour générer une réponse.
    """
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Construction du prompt système
    system_prompt = {
        "role": "system", 
        "content": "Tu es WikiMind, une IA participant à une conversation de groupe. Tu es utile, concis et amical. Tu ne réponds que si on t'interpelle directement. Utilise le format Markdown."
    }
    
    messages = [system_prompt] + context_history
    
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "temperature": 0.7
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Erreur IA: {e}")
        return "Désolé, mes circuits sont surchargés. Je ne peux pas répondre pour le moment."

# --- WEBSOCKET ENDPOINT ---
@app.websocket("/ws/{room_id}/{username}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, username: str):
    await manager.connect(websocket, room_id)
    
    # Annonce de connexion
    await manager.broadcast({
        "author": "Système",
        "content": f"{username} a rejoint la conversation.",
        "type": "info",
        "is_ai": False
    }, room_id)

    try:
        while True:
            data = await websocket.receive_text()
            # On attend un message simple texte du client
            
            # Diffusion du message utilisateur
            await manager.broadcast({
                "author": username,
                "content": data,
                "type": "message",
                "is_ai": False
            }, room_id)

            # Détection du tag @wikimind
            if "@wikimind" in data.lower():
                # Récupération du contexte
                history = manager.get_history(room_id)
                
                # Génération de la réponse
                ai_response = ask_wikimind_ai(history, data)
                
                # Diffusion de la réponse IA
                await manager.broadcast({
                    "author": "WikiMind",
                    "content": ai_response,
                    "type": "message",
                    "is_ai": True
                }, room_id)

    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)
        await manager.broadcast({
            "author": "Système",
            "content": f"{username} a quitté la conversation.",
            "type": "info",
            "is_ai": False
        }, room_id)

if __name__ == "__main__":
    import uvicorn
    print("🚀 Serveur WikiMind Shared Chat démarré sur port 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
