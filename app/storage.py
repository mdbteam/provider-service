# app/storage.py
import os
import json
import uuid
from fastapi import UploadFile, HTTPException, status
from google.cloud import storage
from google.oauth2 import service_account

gcs_credentials_str = os.environ.get("GCS_CREDENTIALS")
if not gcs_credentials_str:
    raise RuntimeError("La variable de entorno GCS_CREDENTIALS no está configurada.")

try:
    gcs_credentials_dict = json.loads(gcs_credentials_str)
except json.JSONDecodeError:
    raise RuntimeError("GCS_CREDENTIALS no es un JSON válido.")

credentials = service_account.Credentials.from_service_account_info(gcs_credentials_dict)
storage_client = storage.Client(credentials=credentials)

BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")
if not BUCKET_NAME:
    raise RuntimeError("La variable de entorno GCS_BUCKET_NAME no está configurada.")

def upload_file_and_get_url(file: UploadFile, user_id: int, file_type: str) -> str:
    if not file.filename:
        return ""
    try:
        bucket = storage_client.get_bucket(BUCKET_NAME)
        unique_name = f"{uuid.uuid4().hex[:10]}_{file.filename.replace(' ', '_')}"
        destination_blob_name = f"{file_type}/{user_id}/{unique_name}"
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_file(file.file, content_type=file.content_type)
        return blob.public_url
    except Exception as e:
        print(f"Error al subir a GCS: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo subir el archivo al almacenamiento en la nube."
        )