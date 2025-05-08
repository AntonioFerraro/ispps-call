import os
from aiohttp import web
from azure.core.messaging import CloudEvent
from azure.communication.callautomation import (
    CallAutomationClient,
    PhoneNumberIdentifier,
    MediaStreamingOptions,
    MediaStreamingTransportType,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
    AudioFormat,
)


class AcsCaller:
    def __init__(self, source_number: str, connection_string: str, callback_url: str, websocket_path: str):
        self.source_number = source_number
        self.acs_connection_string = connection_string
        self.callback_url = callback_url

        # Normalize base + path
        base_url = os.environ.get("ACS_BASE_URL", "").rstrip("/")
        path = websocket_path.lstrip("/")
        self.websocket_url = f"{base_url}/{path}"
        print(f"📡 ACS transport URL: {self.websocket_url}")  # Log importantissimo

        self.call_automation_client = CallAutomationClient.from_connection_string(self.acs_connection_string)

        self.media_streaming_configuration = MediaStreamingOptions(
            transport_url=self.websocket_url,
            transport_type=MediaStreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=MediaStreamingAudioChannelType.MIXED,
            start_media_streaming=True,
            enable_bidirectional=True,
            audio_format=AudioFormat.PCM24_K_MONO
        )

    async def initiate_call(self, target_number: str):
        print(f"📞 Avvio chiamata verso {target_number}")
        target = PhoneNumberIdentifier(target_number)
        source = PhoneNumberIdentifier(self.source_number)

        self.call_automation_client.create_call(
            target,
            self.callback_url,
            media_streaming=self.media_streaming_configuration,
            source_caller_id_number=source
        )

    async def outbound_call_handler(self, request: web.Request):
        cloudevent = await request.json()
        for event_dict in cloudevent:
            event = CloudEvent.from_dict(event_dict)
            if event.data is None:
                continue

            call_connection_id = event.data.get("callConnectionId", "???")
            print(f"📨 Evento ricevuto: {event.type} (CallConnectionId: {call_connection_id})")

            if event.type == "Microsoft.Communication.CallConnected":
                print("✅ Chiamata connessa – ci si aspetta apertura WebSocket da ACS ora!")

        return web.Response(status=200)
