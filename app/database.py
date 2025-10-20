# app/database.py
import pyodbc
import os
from fastapi import HTTPException, status

CONNECTION_STRING = os.environ.get("DATABASE_CONNECTION_STRING")

def get_db_connection():
    if not CONNECTION_STRING:
        raise HTTPException(status_code=500, detail="Cadena de conexión no configurada.")
    conn = None
    try:
        conn = pyodbc.connect(CONNECTION_STRING, autocommit=False)
        yield conn
    except pyodbc.Error as e:
        raise HTTPException(status_code=503, detail=f"No se pudo conectar a la base de datos: {e}")
    finally:
        if conn:
            conn.close()