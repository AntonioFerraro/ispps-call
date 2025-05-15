import os
import json
from azure.storage.blob import BlobServiceClient
from datetime import datetime, timezone

connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
container_name = os.environ.get("AZURE_STORAGE_CONTAINER")

blob_service_client = BlobServiceClient.from_connection_string(connection_string)

def log_conversation(call_id: str, messages: list[dict]):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H_%M_%SZ")
    filename = f"{call_id}/conversation_{timestamp}.json"

    blob_client = blob_service_client.get_blob_client(container=container_name, blob=filename)

    try:
        blob_client.upload_blob(json.dumps({
            "call_id": call_id,
            "timestamp": timestamp,
            "messages": messages
        }, indent=2), overwrite=True)
        print(f"\U0001f4dd Log JSON salvato: {filename}")
    except Exception as e:
        print(f"\u274c Errore salvataggio JSON su blob: {e}")
