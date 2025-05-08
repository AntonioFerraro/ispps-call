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
    source_number: str
    acs_connection_string: str
    callback_uri: str
    websocket_url: str
    media_streaming_configuration: MediaStreamingOptions

    def __init__(self, source_number: str, acs_connection_string: str, acs_callback_path: str, acs_media_streaming_websocket_path: str):
        self.source_number = source_number
        self.acs_connection_string = acs_connection_string

        base_url = os.environ.get("ACS_BASE_URL")
        if not base_url:
            raise ValueError("Missing ACS_BASE_URL environment variable")

        self.callback_uri = base_url.rstrip("/") + acs_callback_path
        self.websocket_url = base_url.rstrip("/").replace("https://", "wss://") + acs_media_streaming_websocket_path

        print(f"📞 Callback URI: {self.callback_uri}")
        print(f"🎙️  WebSocket URL: {self.websocket_url}")

        self.media_streaming_configuration = MediaStreamingOptions(
            transport_url=self.websocket_url,
            transport_type=MediaStreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=MediaStreamingAudioChannelType.MIXED,
            start_media_streaming=True,
            enable_bidirectional=True,
            audio_format=AudioFormat.PCM24_K_MONO,
        )

    async def initiate_call(self, target_number: str):
        print(f"📲 Inizio chiamata verso: {target_number}")
        self.call_automation_client = CallAutomationClient.from_connection_string(self.acs_connection_string)
        target_participant = PhoneNumberIdentifier(target_number)
        source_caller = PhoneNumberIdentifier(self.source_number)

        print("📤 Chiamata in corso...")
        self.call_automation_client.create_call(
            target_participant,
            self.callback_uri,
            media_streaming=self.media_streaming_configuration,
            source_caller_id_number=source_caller,
        )
        print("✅ create_call invocato")

    async def outbound_call_handler(self, request):
        cloudevent = await request.json()
        for event_dict in cloudevent:
            event = CloudEvent.from_dict(event_dict)
            if event.data is None:
                continue

            call_connection_id = event.data.get("callConnectionId")
            print(f"📨 {event.type} ricevuto (CallConnectionId: {call_connection_id})")

            if event.type == "Microsoft.Communication.CallConnected":
                print("🔗 Chiamata connessa – attesa connessione WebSocket da ACS...")

        return web.Response(status=200)
