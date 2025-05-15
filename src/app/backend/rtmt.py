import aiohttp
import asyncio
import json
from typing import Any, Optional
from aiohttp import ClientWebSocketResponse, web
from azure.identity import DefaultAzureCredential, AzureDeveloperCliCredential, get_bearer_token_provider
from azure.core.credentials import AzureKeyCredential
from backend.tools.tools import RTToolCall, Tool, ToolResultDirection
from backend.helpers import transform_acs_to_openai_format, transform_openai_to_acs_format
import time
from datetime import datetime, timezone

class RTMiddleTier:
    endpoint: str
    deployment: str
    key: Optional[str] = None
    selected_voice: str = "alloy"
    tools: dict[str, Tool] = {}
    model: Optional[str] = None
    system_message: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    disable_audio: Optional[bool] = None

    _tools_pending: dict[str, RTToolCall] = {}
    _token_provider = None

    def __init__(self, endpoint: str, deployment: str, credentials: AzureKeyCredential | AzureDeveloperCliCredential | DefaultAzureCredential):
        self.endpoint = endpoint
        self.deployment = deployment
        if isinstance(credentials, AzureKeyCredential):
            self.key = credentials.key
        else:
            self._token_provider = get_bearer_token_provider(credentials, "https://cognitiveservices.azure.com/.default")
            self._token_provider()

    async def _process_message_to_client(self, message: Any, client_ws: web.WebSocketResponse, server_ws: ClientWebSocketResponse, is_acs_audio_stream: bool):
        if message is not None:
            match message["type"]:
                case "session.updated":
                    print("Sessione aggiornata → forzo risposta dell'AI")
                    await server_ws.send_json({ "type": "response.create" })

                case "response.audio.delta":
                    print("Ricevuto audio delta da OpenAI")

                case "response.output_item.added":
                    if "item" in message and message["item"]["type"] == "function_call":
                        message = None

                case "conversation.item.created":
                    if "item" in message and message["item"]["type"] in ["function_call", "function_call_output"]:
                        message = None

                case "response.output_item.done":
                    print("Fine della risposta")
                    if len(self._tools_pending) > 0:
                        self._tools_pending.clear()
                        await server_ws.send_json({ "type": "response.create" })

                case "input_audio_buffer.speech_started":
                    print("Utente ha iniziato a parlare (interruzione)")

        if is_acs_audio_stream and message is not None:
            original_type = message.get("type")
            message = transform_openai_to_acs_format(message)
            if original_type == "response.audio.delta":
                print("➡️ Audio trasformato per ACS e pronto all'invio")

        if message is not None:
            await client_ws.send_str(json.dumps(message))
            if is_acs_audio_stream:
                print(f"📤 Inviato a ACS → tipo: {message.get('type')}")

    async def _process_message_to_server(self, data: Any, ws: web.WebSocketResponse, server_ws: ClientWebSocketResponse, is_acs_audio_stream: bool):
        if is_acs_audio_stream:
            data = transform_acs_to_openai_format(
                data, self.model, self.tools, self.system_message,
                self.temperature, self.max_tokens, self.disable_audio,
                self.selected_voice
            )

        if data is not None:
            match data["type"]:
                case "session.update":
                    session = data["session"]
                    session["voice"] = self.selected_voice
                    if self.system_message:
                        session["instructions"] = self.system_message
                    if self.temperature is not None:
                        session["temperature"] = self.temperature
                    if self.max_tokens is not None:
                        session["max_response_output_tokens"] = self.max_tokens
                    if self.disable_audio is not None:
                        session["disable_audio"] = self.disable_audio
                    session["tool_choice"] = "auto" if len(self.tools) > 0 else "none"
                    session["tools"] = [tool.schema for tool in self.tools.values()]
                    data["session"] = session

            await server_ws.send_str(json.dumps(data))

    async def forward_messages(self, ws: web.WebSocketResponse, is_acs_audio_stream: bool, request: Optional[web.Request] = None) -> list[dict]:
        messages: list[dict] = []

        raw_call_id = request.query.get("callConnectionId", "unknown-call") if request else "unknown-call"
        call_id = "".join(c for c in raw_call_id if c.isalnum() or c in ("-", "_"))
        start_time = time.time()

        print(f"🟢 forward_messages avviato – call_id: {call_id}, ACS: {is_acs_audio_stream}")

        async with aiohttp.ClientSession(base_url=self.endpoint) as session:
            params = {
                "api-version": "2024-10-01-preview",
                "deployment": self.deployment
            }

            headers = {}
            if "x-ms-client-request-id" in ws.headers:
                headers["x-ms-client-request-id"] = ws.headers["x-ms-client-request-id"]

            if self.key is not None:
                headers = { "api-key": self.key }
            elif self._token_provider is not None:
                headers = { "Authorization": f"Bearer {self._token_provider()}" }
            else:
                raise ValueError("No token provider available")

            async with session.ws_connect("/openai/realtime", headers=headers, params=params) as target_ws:
                print("🔗 Connessione a OpenAI Realtime stabilita")

                async def from_client_to_server():
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            print(f"⬅️ [CLIENT → SERVER] Ricevuto: {data}")

                            # ✅ Log user messages – anche da ACS se contiene testo
                            if data.get("type") == "conversation.input":
                                text = data.get("input", {}).get("text")
                                if text:
                                    messages.append({
                                        "call_id": call_id,
                                        "role": "user",
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                        "content": text
                                    })
                                    print(f"📝 [LOG] Utente (text): {messages[-1]}")

                            await self._process_message_to_server(data, ws, target_ws, is_acs_audio_stream)
                        else:
                            print(f"⚠️ Messaggio client ignorato: {msg.type}")

                async def from_server_to_client():
                    async for msg in target_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            print(f"➡️ [SERVER → CLIENT] Ricevuto: {data}")

                            if data.get("type") == "conversation.output":
                                messages.append({
                                    "call_id": call_id,
                                    "role": "assistant",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "content": data.get("text", "[empty]")
                                })
                                print(f"📝 [LOG] Assistant (text): {messages[-1]}")

                            await self._process_message_to_client(data, ws, target_ws, is_acs_audio_stream)
                        else:
                            print(f"⚠️ Messaggio server ignorato: {msg.type}")

                try:
                    await asyncio.gather(from_client_to_server(), from_server_to_client())
                except ConnectionResetError:
                    print("🔌 Connessione WebSocket terminata dal client")
                except Exception as e:
                    print(f"❌ Errore durante lo scambio WebSocket: {e}")

        duration_sec = round(time.time() - start_time, 2)
        messages.append({
            "call_id": call_id,
            "role": "system",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "content": f"Durata sessione: {duration_sec} secondi"
        })

        print(f"📦 Conversazione terminata. Messaggi totali: {len(messages)}")
        return messages