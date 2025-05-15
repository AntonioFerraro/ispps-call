import os
import json
from azure.storage.blob import BlobServiceClient
from datetime import datetime, timezone
from json import JSONEncoder

# Config da env
connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
container_name = os.environ.get("AZURE_STORAGE_CONTAINER")

blob_service_client = BlobServiceClient.from_connection_string(connection_string)

# Encoder custom per supportare datetime, timezone, ecc.
class SafeJSONEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

def log_conversation(call_id: str, messages: list[dict]):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H_%M_%SZ")
    filename = f"{call_id}/conversation_{timestamp}.json"
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=filename)

    try:
        json_data = json.dumps({
            "call_id": call_id,
            "timestamp": timestamp,
            "messages": messages
        }, indent=2, cls=SafeJSONEncoder)

        blob_client.upload_blob(json_data, overwrite=True)
        print(f"📝 Log JSON salvato: {filename}")
    except Exception as e:
        print(f"❌ Errore salvataggio JSON su blob: {e}")
        print("🔍 Dump parziale JSON (debug):")
        try:
            print(json.dumps(messages[:2], indent=2, cls=SafeJSONEncoder))  # Mostra i primi 2 msg per debug
        except Exception as inner:
            print(f"⚠️ Fallita anche serializzazione parziale: {inner}")