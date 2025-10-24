# provider-service/app/main.py
from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile
from typing import List
import pyodbc
from dotenv import load_dotenv
from datetime import date # Importar date

load_dotenv(override=True)

from app.database import get_db_connection
# Importamos UserPublic y ProfileUpdate
from app.models import (
    PrestadorResumen, UserInDB, ProfileDetail, PostulacionForm, PostulacionResponse,
    TrabajoCreate, TrabajoDetail, ValoracionTrabajoCreate, TrabajoHistorial, UserPublic,
    ProfileUpdate
)
# Importamos la dependencia correcta
from app.auth_utils import get_current_active_user, get_current_admin_user
from app.storage import upload_file_and_get_url

app = FastAPI(
    title="Servicio de Prestadores - Chambee",
    description="Gestiona perfiles, postulaciones y trabajos de los prestadores.",
    version="1.0.0"
)

# Constantes
ROLE_PROVEEDOR = 2
ROLE_HYBRID = 3
ROLE_CLIENTE = 1
STATUS_ACTIVO = 'activo'
STATUS_PENDIENTE = 'pendiente'

@app.get("/", tags=["Status"])
def root():
    return {"message": "Provider Service funcionando 🚀"}

# --- ENDPOINTS DE VISUALIZACIÓN ---
@app.get("/prestadores", response_model=List[PrestadorResumen], tags=["Prestadores"])
def get_all_prestadores(conn: pyodbc.Connection = Depends(get_db_connection)):
    """Obtiene una lista resumida de todos los prestadores activos."""
    cursor = conn.cursor()
    query = """
        SELECT
            u.id_usuario, u.nombres, u.primer_apellido, u.foto_url,
            p.resumen_profesional,
            (SELECT STRING_AGG(o.nombre_oficio, ', ') FROM Oficio o WHERE o.id_usuario = u.id_usuario) AS oficios,
            ISNULL(AVG(CAST(v.puntaje AS FLOAT)), 0) AS puntuacion_promedio
        FROM Usuarios u
        LEFT JOIN Perfil p ON u.id_usuario = p.id_usuario
        LEFT JOIN Valoraciones v ON u.id_evaluado = u.id_usuario AND v.rol_autor = 'cliente'
        WHERE u.id_rol IN (?, ?) AND u.estado = 'activo'
        GROUP BY u.id_usuario, u.nombres, u.primer_apellido, u.foto_url, p.resumen_profesional
        ORDER BY puntuacion_promedio DESC;
    """
    try:
        cursor.execute(query, ROLE_PROVEEDOR, ROLE_HYBRID)
        rows = cursor.fetchall()
        prestadores = [
            PrestadorResumen(
                id=str(row.id_usuario),
                nombres=row.nombres,
                primer_apellido=row.primer_apellido,
                foto_url=row.foto_url,
                oficios=row.oficios.split(', ') if row.oficios else [],
                resumen=row.resumen_profesional,
                puntuacion=round(row.puntuacion_promedio, 1)
            ) for row in rows
        ]
        return prestadores
    except pyodbc.Error as e:
        raise HTTPException(status_code=500, detail=f"Error en la base de datos: {e}")
    finally:
        cursor.close()

# --- ENDPOINT /users/me UNIFICADO ---
@app.get("/users/me", response_model=UserPublic, tags=["Perfil"])
def read_users_me(current_user: UserInDB = Depends(get_current_active_user)):
    """Devuelve los datos públicos COMPLETOS del usuario autenticado."""
    rol_map = {0: "administrador", 1: "cliente", 2: "prestador", 3: "híbrido"}
    rol_str = rol_map.get(current_user.id_rol, "desconocido")
    return UserPublic(
        id=str(current_user.id_usuario),
        nombres=current_user.nombres,
        primer_apellido=current_user.primer_apellido,
        segundo_apellido=current_user.segundo_apellido,
        rut=current_user.rut,
        correo=current_user.correo,
        direccion=current_user.direccion,
        rol=rol_str,
        foto_url=current_user.foto_url,
        genero=current_user.genero,
        fecha_nacimiento=current_user.fecha_nacimiento
    )
# --- FIN ENDPOINT /users/me ---

@app.put("/profile/me/picture", tags=["Perfil"])
def update_profile_picture(file: UploadFile = File(...), current_user: UserInDB = Depends(get_current_active_user),
                           conn: pyodbc.Connection = Depends(get_db_connection)):
    """Actualiza la foto de perfil del usuario autenticado."""
    user_id = current_user.id_usuario
    photo_url = upload_file_and_get_url(file, user_id, "perfil")
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE Usuarios SET foto_url = ? WHERE id_usuario = ?", photo_url, user_id)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=f"Error al actualizar la foto: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Foto de perfil actualizada", "foto_url": photo_url}

# --- ENDPOINT PATCH /profile/me ---
@app.patch("/profile/me", response_model=UserPublic, tags=["Perfil"])
def update_my_profile(
    profile_data: ProfileUpdate,
    current_user: UserInDB = Depends(get_current_active_user),
    conn: pyodbc.Connection = Depends(get_db_connection)
):
    """Actualiza dirección, biografía o correo del usuario autenticado."""
    user_id = current_user.id_usuario
    cursor = conn.cursor()

    user_updates = []
    user_values = []
    perfil_updates = []
    perfil_values = []
    perfil_insert_cols = []
    perfil_insert_placeholders = []

    # Validar Correo Nuevo (si se proporciona)
    if profile_data.correo is not None and profile_data.correo != current_user.correo:
        cursor.execute("SELECT id_usuario FROM Usuarios WHERE correo = ? AND id_usuario != ?", profile_data.correo, user_id)
        if cursor.fetchone():
            cursor.close() # Cerramos antes de lanzar excepción
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El nuevo correo electrónico ya está en uso por otro usuario.")
        user_updates.append("correo = ?"); user_values.append(profile_data.correo)

    # Añadir otros campos permitidos
    if profile_data.direccion is not None:
        user_updates.append("direccion = ?"); user_values.append(profile_data.direccion)
    if profile_data.biografia is not None:
        perfil_updates.append("biografia = ?"); perfil_values.append(profile_data.biografia)
        perfil_insert_cols.append("biografia"); perfil_insert_placeholders.append("?")

    # Verificar si hay algo que actualizar
    if not user_updates and not perfil_updates:
        cursor.close() # Cerramos si no hay nada que hacer
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No se proporcionaron datos válidos para actualizar.")

    try:
        if user_updates:
            user_query = f"UPDATE Usuarios SET {', '.join(user_updates)} WHERE id_usuario = ?"
            cursor.execute(user_query, tuple(user_values + [user_id]))

        if perfil_updates:
            perfil_query = f"""
                MERGE Perfil AS target
                USING (SELECT ? AS id_usuario) AS source ON (target.id_usuario = source.id_usuario)
                WHEN MATCHED THEN UPDATE SET {', '.join(perfil_updates)}
                WHEN NOT MATCHED THEN INSERT (id_usuario, {', '.join(perfil_insert_cols)}) VALUES (?, {', '.join(perfil_insert_placeholders)});
            """
            cursor.execute(perfil_query, tuple([user_id] + perfil_values + [user_id] + perfil_values))

        conn.commit()
    except pyodbc.Error as e:
        conn.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error en BBDD al actualizar perfil: {e}")
    finally:

        if cursor: cursor.close()

    new_conn = None
    new_cursor = None
    try:
        new_conn = get_db_connection().__next__() # Obtener nueva conexión
        new_cursor = new_conn.cursor()
        new_cursor.execute("""
            SELECT id_usuario, nombres, primer_apellido, segundo_apellido, rut, correo,
                   direccion, id_rol, estado, foto_url, genero, fecha_nacimiento
            FROM Usuarios WHERE id_usuario = ?
            """, user_id)
        updated_user_record = new_cursor.fetchone()
    except Exception as e:
         # Si falla la re-consulta, al menos la actualización se hizo
         print(f"WARN: Actualización exitosa, pero error al re-obtener datos: {e}")
         # Devolvemos los datos conocidos antes de la actualización como fallback
         rol_map = {0: "administrador", 1: "cliente", 2: "prestador", 3: "híbrido"}
         rol_str = rol_map.get(current_user.id_rol, "desconocido")
         return UserPublic(
             id=str(user_id), nombres=current_user.nombres, primer_apellido=current_user.primer_apellido,
             segundo_apellido=current_user.segundo_apellido, rut=current_user.rut,
             correo=profile_data.correo if profile_data.correo else current_user.correo, # Usar el nuevo correo si cambió
             direccion=profile_data.direccion if profile_data.direccion else current_user.direccion, # Usar nueva dir si cambió
             rol=rol_str, foto_url=current_user.foto_url, genero=current_user.genero,
             fecha_nacimiento=current_user.fecha_nacimiento
         )
    finally:
        if new_cursor: new_cursor.close()
        if new_conn: new_conn.close()


    if not updated_user_record:
        raise HTTPException(status_code=404, detail="Usuario no encontrado después de actualizar.")

    rol_map = {0: "administrador", 1: "cliente", 2: "prestador", 3: "híbrido"}
    rol_str = rol_map.get(updated_user_record.id_rol, "desconocido")

    # Mapeamos a UserPublic
    return UserPublic(
        id=str(updated_user_record.id_usuario),
        nombres=updated_user_record.nombres,
        primer_apellido=updated_user_record.primer_apellido,
        segundo_apellido=updated_user_record.segundo_apellido,
        rut=updated_user_record.rut,
        correo=updated_user_record.correo,
        direccion=updated_user_record.direccion,
        rol=rol_str,
        foto_url=updated_user_record.foto_url,
        genero=updated_user_record.genero,
        fecha_nacimiento=updated_user_record.fecha_nacimiento
    )
# --- FIN ENDPOINT PATCH ---


# --- ENDPOINTS DE POSTULACIÓN ---
@app.post("/postulaciones", response_model=PostulacionResponse, tags=["Postulaciones"])
def send_postulacion(form: PostulacionForm = Depends(), current_user: UserInDB = Depends(get_current_active_user), conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    user_id = current_user.id_usuario
    try:
        cursor.execute("UPDATE Usuarios SET nombres = ?, primer_apellido = ?, segundo_apellido = ?, direccion = ? WHERE id_usuario = ?",
                       form.nombres, form.primer_apellido, form.segundo_apellido, form.direccion, user_id)
        cursor.execute("DELETE FROM Portafolio WHERE id_usuario = ?", user_id)
        cursor.execute("DELETE FROM Certificaciones WHERE id_usuario = ?", user_id)
        cursor.execute("DELETE FROM Oficio WHERE id_usuario = ?", user_id)

        for file in form.archivos_portafolio:
            if file.filename:
                url = upload_file_and_get_url(file, user_id, "portafolio")
                cursor.execute("INSERT INTO Portafolio (id_usuario, enlace_imagen, descripcion) VALUES (?, ?, ?)", user_id, url, file.filename)
        for file in form.archivos_certificados:
            if file.filename:
                url = upload_file_and_get_url(file, user_id, "certificado")
                cursor.execute("INSERT INTO Certificaciones (id_usuario, nombre_certificacion, enlace_documento) VALUES (?, ?, ?)", user_id, file.filename, url)
        cursor.execute("MERGE Perfil AS target USING (SELECT ? AS id_usuario) AS source ON (target.id_usuario = source.id_usuario) "
                       "WHEN MATCHED THEN UPDATE SET biografia = ?, resumen_profesional = ? "
                       "WHEN NOT MATCHED THEN INSERT (id_usuario, biografia, resumen_profesional) VALUES (?, ?, ?);",
                       user_id, form.bio, form.oficio, user_id, form.bio, form.oficio)
        oficios = [o.strip() for o in form.oficio.split(',') if o.strip()]
        for oficio_nombre in oficios:
            cursor.execute("INSERT INTO Oficio (id_usuario, nombre_oficio) VALUES (?, ?)", user_id, oficio_nombre)
        cursor.execute("MERGE Postulaciones AS target USING (SELECT ? as id_usuario) AS source ON (target.id_usuario = source.id_usuario) "
                       "WHEN MATCHED THEN UPDATE SET estado = ?, fecha_postulacion = GETDATE() "
                       "WHEN NOT MATCHED THEN INSERT (id_usuario, estado) VALUES (?, ?);",
                       user_id, STATUS_PENDIENTE, user_id, STATUS_PENDIENTE)
        cursor.execute("UPDATE Usuarios SET estado = ? WHERE id_usuario = ?", STATUS_PENDIENTE, user_id)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=f"Error en BBDD Postulación: {e}")
    finally:
        cursor.close()
    return PostulacionResponse(mensaje="Postulación enviada exitosamente.", statusPostulacion=STATUS_PENDIENTE)

@app.post("/admin/postulaciones/{id_postulacion}/aprobar", tags=["Administración"])
def approve_postulacion(id_postulacion: int, admin_user: UserInDB = Depends(get_current_admin_user), conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT p.id_usuario, u.id_rol FROM Postulaciones p JOIN Usuarios u ON p.id_usuario = u.id_usuario WHERE p.id_postulacion = ? AND p.estado = ?",
                       id_postulacion, STATUS_PENDIENTE)
        postulacion = cursor.fetchone()
        if not postulacion: raise HTTPException(status_code=404, detail="Postulación no encontrada o ya procesada.")
        id_usuario, rol_actual = postulacion.id_usuario, postulacion.id_rol
        nuevo_rol = ROLE_HYBRID if rol_actual == ROLE_CLIENTE else rol_actual
        cursor.execute("UPDATE Usuarios SET estado = ?, id_rol = ? WHERE id_usuario = ?", STATUS_ACTIVO, nuevo_rol, id_usuario)
        cursor.execute("UPDATE Postulaciones SET estado = 'aprobada' WHERE id_postulacion = ?", id_postulacion)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=f"Error al aprobar: {e}")
    finally:
        cursor.close()
    return {"mensaje": f"Postulación {id_postulacion} aprobada. El usuario {id_usuario} ahora es prestador."}

# --- ENDPOINTS DE TRABAJOS (CONTRATOS) ---
@app.post("/trabajos", response_model=TrabajoDetail, status_code=status.HTTP_201_CREATED, tags=["Trabajos"])
def propose_trabajo(trabajo_data: TrabajoCreate, current_user: UserInDB = Depends(get_current_active_user), conn: pyodbc.Connection = Depends(get_db_connection)):
    """Propone un nuevo trabajo/contrato."""
    if current_user.id_usuario not in [trabajo_data.id_cliente, trabajo_data.id_prestador]:
        raise HTTPException(status_code=403, detail="No tienes permiso para proponer este trabajo.")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO Trabajos (id_cita, id_cliente, id_prestador, descripcion, condiciones, precio_acordado) OUTPUT INSERTED.* VALUES (?, ?, ?, ?, ?, ?)",
                       trabajo_data.id_cita, trabajo_data.id_cliente, trabajo_data.id_prestador, trabajo_data.descripcion, trabajo_data.condiciones, trabajo_data.precio_acordado)
        new_trabajo = cursor.fetchone()
        conn.commit()
        trabajo_dict = dict(zip([column[0] for column in new_trabajo.cursor_description], new_trabajo))
        return TrabajoDetail(**trabajo_dict)
    except pyodbc.Error as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=f"Error en la BBDD: {e}")
    finally:
        cursor.close()

@app.post("/trabajos/{id_trabajo}/aceptar", response_model=TrabajoDetail, tags=["Trabajos"])
def accept_trabajo(id_trabajo: int, current_user: UserInDB = Depends(get_current_active_user), conn: pyodbc.Connection = Depends(get_db_connection)):
    """Permite al cliente aceptar un trabajo propuesto."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Trabajos WHERE id_trabajo = ?", id_trabajo)
    trabajo = cursor.fetchone()
    if not trabajo: raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if current_user.id_usuario != trabajo.id_cliente: raise HTTPException(status_code=403, detail="Solo el cliente puede aceptar.")
    if trabajo.estado != 'propuesto': raise HTTPException(status_code=400, detail="Trabajo no puede ser aceptado.")
    try:
        cursor.execute("UPDATE Trabajos SET estado = 'aceptado', fecha_aceptacion = GETDATE() OUTPUT INSERTED.* WHERE id_trabajo = ?", id_trabajo)
        updated_trabajo = cursor.fetchone()
        conn.commit()
        trabajo_dict = dict(zip([column[0] for column in updated_trabajo.cursor_description], updated_trabajo))
        return TrabajoDetail(**trabajo_dict)
    except pyodbc.Error as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=f"Error en la BBDD: {e}")
    finally:
        cursor.close()

@app.post("/trabajos/{id_trabajo}/finalizar", tags=["Trabajos"])
def finalize_trabajo_by_prestador(id_trabajo: int, current_user: UserInDB = Depends(get_current_active_user), conn: pyodbc.Connection = Depends(get_db_connection)):
    """(Solo Prestador) Marca un trabajo como finalizado."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Trabajos WHERE id_trabajo = ?", id_trabajo)
    trabajo = cursor.fetchone()
    if not trabajo: raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if current_user.id_usuario != trabajo.id_prestador: raise HTTPException(status_code=403, detail="Solo el prestador puede finalizar.")
    if trabajo.estado not in ['aceptado', 'en_progreso']: raise HTTPException(status_code=400, detail="Solo se puede finalizar un trabajo aceptado.")
    try:
        cursor.execute("UPDATE Trabajos SET estado = 'finalizado_por_prestador', fecha_finalizacion_prestador = GETDATE() WHERE id_trabajo = ?", id_trabajo)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=f"Error en la BBDD: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Trabajo marcado como finalizado por prestador."}

@app.post("/trabajos/{id_trabajo}/confirmar", tags=["Trabajos"])
def confirm_trabajo_by_cliente(id_trabajo: int, current_user: UserInDB = Depends(get_current_active_user), conn: pyodbc.Connection = Depends(get_db_connection)):
    """(Solo Cliente) Confirma la finalización y activa valoraciones."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Trabajos WHERE id_trabajo = ?", id_trabajo)
    trabajo = cursor.fetchone()
    if not trabajo: raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if current_user.id_usuario != trabajo.id_cliente: raise HTTPException(status_code=403, detail="Solo el cliente puede confirmar.")
    if trabajo.estado != 'finalizado_por_prestador': raise HTTPException(status_code=400, detail="El prestador aún no ha finalizado.")
    try:
        cursor.execute("UPDATE Trabajos SET estado = 'completado', fecha_finalizacion_cliente = GETDATE() WHERE id_trabajo = ?", id_trabajo)
        cursor.execute("UPDATE Usuarios SET trabajos_realizados = trabajos_realizados + 1 WHERE id_usuario = ?", trabajo.id_prestador)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=f"Error en la BBDD: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Trabajo completado. Ahora pueden valorarse."}

@app.post("/trabajos/{id_trabajo}/valorar", tags=["Trabajos"])
def valorar_trabajo(id_trabajo: int, valoracion: ValoracionTrabajoCreate, current_user: UserInDB = Depends(get_current_active_user), conn: pyodbc.Connection = Depends(get_db_connection)):
    """Permite valorar un trabajo completado."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Trabajos WHERE id_trabajo = ?", id_trabajo)
    trabajo = cursor.fetchone()
    if not trabajo: raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if trabajo.estado != 'completado': raise HTTPException(status_code=400, detail="Solo trabajos completados.")
    if current_user.id_usuario not in [trabajo.id_cliente, trabajo.id_prestador]: raise HTTPException(status_code=403, detail="No participas.")

    id_autor = current_user.id_usuario
    rol_autor = 'cliente' if id_autor == trabajo.id_cliente else 'prestador'
    id_evaluado = trabajo.id_prestador if rol_autor == 'cliente' else trabajo.id_cliente
    try:
        cursor.execute("SELECT id_valoracion FROM Valoraciones WHERE id_trabajo = ? AND id_autor = ?", id_trabajo, id_autor)
        if cursor.fetchone(): raise HTTPException(status_code=400, detail="Ya has valorado este trabajo.")
        cursor.execute("INSERT INTO Valoraciones (id_trabajo, id_autor, id_evaluado, rol_autor, puntaje, comentario) VALUES (?, ?, ?, ?, ?, ?)",
                       id_trabajo, id_autor, id_evaluado, rol_autor, valoracion.puntaje, valoracion.comentario)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=f"Error en la BBDD: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Valoración enviada."}

@app.get("/prestadores/{id_prestador}/trabajos", response_model=List[TrabajoHistorial], tags=["Prestadores"])
def get_prestador_trabajos_historial(id_prestador: int, conn: pyodbc.Connection = Depends(get_db_connection)):
    """Obtiene el historial de trabajos completados de un prestador."""
    cursor = conn.cursor()
    query = """
        SELECT t.id_trabajo, t.descripcion, t.precio_acordado, t.fecha_finalizacion_cliente,
               v.puntaje AS puntaje_recibido, v.comentario AS comentario_recibido
        FROM Trabajos t
        LEFT JOIN Valoraciones v ON t.id_trabajo = v.id_trabajo AND v.rol_autor = 'cliente'
        WHERE t.id_prestador = ? AND t.estado = 'completado'
        ORDER BY t.fecha_finalizacion_cliente DESC;
    """
    try:
        cursor.execute(query, id_prestador)
        trabajos_db = cursor.fetchall()
        historial = [TrabajoHistorial(**dict(zip([column[0] for column in row.cursor_description], row))) for row in trabajos_db]
        return historial
    except pyodbc.Error as e:
        raise HTTPException(status_code=500, detail=f"Error BBDD: {e}")
    finally:
        cursor.close()