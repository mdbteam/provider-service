# provider-service/app/auth_utils.py
import os
from typing import Optional
from fastapi import Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import pyodbc
from app.database import get_db_connection
from app.models import UserInDB # Ensure UserInDB includes all needed fields
from datetime import date # Import date

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY: raise RuntimeError("SECRET_KEY no configurada.")
ALGORITHM = "HS256"
# The tokenUrl points to the auth service, used mainly for documentation
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

async def get_current_user_from_token(token: str = Depends(oauth2_scheme), conn: pyodbc.Connection = Depends(get_db_connection)) -> Optional[UserInDB]:
    """Validates the token and returns the user data if valid."""
    if token is None: return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        # Optional: Add 'iat' check here if needed later, using token_valido_desde
        if user_id is None: return None
    except JWTError: return None

    cursor = conn.cursor()
    # Fetch all necessary fields for UserInDB model
    cursor.execute("""
        SELECT id_usuario, nombres, primer_apellido, segundo_apellido, rut, correo,
               direccion, id_rol, estado, foto_url, genero, fecha_nacimiento, telefono
        FROM Usuarios WHERE id_usuario = ?
        """, int(user_id))
    user_record = cursor.fetchone()
    cursor.close()
    if user_record is None: return None

    # Map the database record to the UserInDB model
    user_data = dict(zip([column[0] for column in user_record.cursor_description], user_record))
    return UserInDB(**user_data)


async def get_current_active_user( # Dependency to get the authenticated active user
    token_from_header: str = Depends(oauth2_scheme),
    token_from_query: str = Query(None, alias="token"),
    conn: pyodbc.Connection = Depends(get_db_connection)
) -> UserInDB:
    """Dependency to get the current active user from header or query token."""
    token = token_from_header or token_from_query
    if not token: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    user = await get_current_user_from_token(token, conn)
    if not user: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")

    # Ensure user is active (can be commented out if inactive users need access to some endpoints)
    if user.estado != 'activo':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo o baneado")

    return user

def get_current_admin_user(current_user: UserInDB = Depends(get_current_active_user)) -> UserInDB:
    """Dependency that ensures the current user is an administrator (role 0)."""
    if current_user.id_rol != 0:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado: Se requieren permisos de administrador.")
    return current_user