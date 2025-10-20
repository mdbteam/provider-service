# app/auth_utils.py
import os
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import pyodbc
from app.database import get_db_connection
from app.models import UserInDB

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY no está configurada.")

ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_current_active_user(token: str = Depends(oauth2_scheme), conn: pyodbc.Connection = Depends(get_db_connection)) -> UserInDB:
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No se pudieron validar las credenciales")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    cursor = conn.cursor()
    cursor.execute("SELECT id_usuario, nombres, primer_apellido, correo, id_rol, estado FROM Usuarios WHERE id_usuario = ?", int(user_id))
    user_record = cursor.fetchone()
    cursor.close()
    if user_record is None:
        raise credentials_exception
    user_in_db = UserInDB(**dict(zip([column[0] for column in user_record.cursor_description], user_record)))
    if user_in_db.estado != 'activo':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")
    return user_in_db

def get_current_admin_user(current_user: UserInDB = Depends(get_current_active_user)) -> UserInDB:
    if current_user.id_rol != 0:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado: Se requieren permisos de administrador.")
    return current_user