# app/main.py
from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile
from typing import List
import pyodbc
from dotenv import load_dotenv

load_dotenv()

from app.database import get_db_connection
from app.models import (
    PrestadorResumen, UserInDB, ProfileDetail, PostulacionForm, PostulacionResponse,
    TrabajoCreate, TrabajoDetail, ValoracionTrabajoCreate,TrabajoHistorial
)
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


@app.get("/profile/me", response_model=ProfileDetail, tags=["Perfil"])
def get_my_profile(current_user: UserInDB = Depends(get_current_active_user),
                   conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    query = """
        SELECT 
            u.id_usuario, u.nombres, u.primer_apellido, u.foto_url,
            u.genero, u.fecha_nacimiento,
            p.biografia, p.resumen_profesional, p.anos_experiencia
        FROM Usuarios u
        LEFT JOIN Perfil p ON u.id_usuario = p.id_usuario
        WHERE u.id_usuario = ?
    """
    try:
        cursor.execute(query, current_user.id_usuario)
        profile_data = cursor.fetchone()
        if not profile_data:
            raise HTTPException(status_code=404, detail="Perfil no encontrado.")
        profile_dict = dict(zip([column[0] for column in profile_data.cursor_description], profile_data))
        return ProfileDetail(**profile_dict)
    except pyodbc.Error as e:
        raise HTTPException(status_code=500, detail=f"Error en la base de datos: {e}")
    finally:
        cursor.close()


@app.put("/profile/me/picture", tags=["Perfil"])
def update_profile_picture(file: UploadFile = File(...), current_user: UserInDB = Depends(get_current_active_user),
                           conn: pyodbc.Connection = Depends(get_db_connection)):
    user_id = current_user.id_usuario
    photo_url = upload_file_and_get_url(file, user_id, "perfil")
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE Usuarios SET foto_url = ? WHERE id_usuario = ?", photo_url, user_id)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error al actualizar la foto: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Foto de perfil actualizada", "foto_url": photo_url}


# --- ENDPOINTS DE POSTULACIÓN ---
@app.post("/postulaciones", response_model=PostulacionResponse, tags=["Postulaciones"])
def send_postulacion(form: PostulacionForm = Depends(), current_user: UserInDB = Depends(get_current_active_user),
                     conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    user_id = current_user.id_usuario
    try:
        cursor.execute(
            "UPDATE Usuarios SET nombres = ?, primer_apellido = ?, segundo_apellido = ?, direccion = ? WHERE id_usuario = ?",
            form.nombres, form.primer_apellido, form.segundo_apellido, form.direccion, user_id)
        for file in form.archivos_portafolio:
            if file.filename:
                url = upload_file_and_get_url(file, user_id, "portafolio")
                cursor.execute("INSERT INTO Portafolio (id_usuario, enlace_imagen, descripcion) VALUES (?, ?, ?)",
                               user_id, url, file.filename)
        for file in form.archivos_certificados:
            if file.filename:
                url = upload_file_and_get_url(file, user_id, "certificado")
                cursor.execute(
                    "INSERT INTO Certificaciones (id_usuario, nombre_certificacion, enlace_documento) VALUES (?, ?, ?)",
                    user_id, file.filename, url)
        cursor.execute(
            "MERGE Perfil AS target USING (SELECT ? AS id_usuario) AS source ON (target.id_usuario = source.id_usuario) "
            "WHEN MATCHED THEN UPDATE SET biografia = ?, resumen_profesional = ? "
            "WHEN NOT MATCHED THEN INSERT (id_usuario, biografia, resumen_profesional) VALUES (?, ?, ?);",
            user_id, form.bio, form.oficio, user_id, form.bio, form.oficio)
        oficios = [o.strip() for o in form.oficio.split(',') if o.strip()]
        for oficio_nombre in oficios:
            cursor.execute("INSERT INTO Oficio (id_usuario, nombre_oficio) VALUES (?, ?)", user_id, oficio_nombre)
        cursor.execute("INSERT INTO Postulaciones (id_usuario, estado) VALUES (?, ?)", user_id, STATUS_PENDIENTE)
        cursor.execute("UPDATE Usuarios SET estado = ? WHERE id_usuario = ?", STATUS_PENDIENTE, user_id)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error en BBDD: {e}")
    finally:
        cursor.close()
    return PostulacionResponse(mensaje="Postulación enviada exitosamente.", statusPostulacion=STATUS_PENDIENTE)


@app.post("/admin/postulaciones/{id_postulacion}/aprobar", tags=["Administración"])
def approve_postulacion(id_postulacion: int, admin_user: UserInDB = Depends(get_current_admin_user),
                        conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT p.id_usuario, u.id_rol FROM Postulaciones p JOIN Usuarios u ON p.id_usuario = u.id_usuario WHERE p.id_postulacion = ? AND p.estado = ?",
            id_postulacion, STATUS_PENDIENTE)
        postulacion = cursor.fetchone()
        if not postulacion: raise HTTPException(status_code=404, detail="Postulación no encontrada o ya procesada.")
        id_usuario, rol_actual = postulacion.id_usuario, postulacion.id_rol
        nuevo_rol = ROLE_HYBRID if rol_actual == ROLE_CLIENTE else rol_actual
        cursor.execute("UPDATE Usuarios SET estado = ?, id_rol = ? WHERE id_usuario = ?", STATUS_ACTIVO, nuevo_rol,
                       id_usuario)
        cursor.execute("UPDATE Postulaciones SET estado = 'aprobada' WHERE id_postulacion = ?", id_postulacion)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error al aprobar: {e}")
    finally:
        cursor.close()
    return {"mensaje": f"Postulación {id_postulacion} aprobada. El usuario {id_usuario} ahora es prestador."}


# --- ENDPOINTS DE TRABAJOS (CONTRATOS) ---
@app.post("/trabajos", response_model=TrabajoDetail, status_code=status.HTTP_201_CREATED, tags=["Trabajos"])
def propose_trabajo(trabajo_data: TrabajoCreate, current_user: UserInDB = Depends(get_current_active_user),
                    conn: pyodbc.Connection = Depends(get_db_connection)):
    if current_user.id_usuario not in [trabajo_data.id_cliente, trabajo_data.id_prestador]:
        raise HTTPException(status_code=403, detail="No tienes permiso para proponer este trabajo.")
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO Trabajos (id_cita, id_cliente, id_prestador, descripcion, condiciones, precio_acordado) OUTPUT INSERTED.* VALUES (?, ?, ?, ?, ?, ?)",
            trabajo_data.id_cita, trabajo_data.id_cliente, trabajo_data.id_prestador, trabajo_data.descripcion,
            trabajo_data.condiciones, trabajo_data.precio_acordado)
        new_trabajo = cursor.fetchone()
        conn.commit()
        trabajo_dict = dict(zip([column[0] for column in new_trabajo.cursor_description], new_trabajo))
        return TrabajoDetail(**trabajo_dict)
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error en la BBDD: {e}")
    finally:
        cursor.close()


@app.post("/trabajos/{id_trabajo}/aceptar", response_model=TrabajoDetail, tags=["Trabajos"])
def accept_trabajo(id_trabajo: int, current_user: UserInDB = Depends(get_current_active_user),
                   conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Trabajos WHERE id_trabajo = ?", id_trabajo)
    trabajo = cursor.fetchone()
    if not trabajo: raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if current_user.id_usuario != trabajo.id_cliente: raise HTTPException(status_code=403,
                                                                          detail="Solo el cliente puede aceptar el trabajo.")
    if trabajo.estado != 'propuesto': raise HTTPException(status_code=400, detail="Este trabajo no puede ser aceptado.")
    try:
        cursor.execute(
            "UPDATE Trabajos SET estado = 'aceptado', fecha_aceptacion = GETDATE() OUTPUT INSERTED.* WHERE id_trabajo = ?",
            id_trabajo)
        updated_trabajo = cursor.fetchone()
        conn.commit()
        trabajo_dict = dict(zip([column[0] for column in updated_trabajo.cursor_description], updated_trabajo))
        return TrabajoDetail(**trabajo_dict)
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error en la BBDD: {e}")
    finally:
        cursor.close()


@app.post("/trabajos/{id_trabajo}/finalizar", tags=["Trabajos"])
def finalize_trabajo_by_prestador(id_trabajo: int, current_user: UserInDB = Depends(get_current_active_user),
                                  conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Trabajos WHERE id_trabajo = ?", id_trabajo)
    trabajo = cursor.fetchone()
    if not trabajo: raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if current_user.id_usuario != trabajo.id_prestador: raise HTTPException(status_code=403,
                                                                            detail="Solo el prestador puede finalizar el trabajo.")
    if trabajo.estado != 'aceptado': raise HTTPException(status_code=400,
                                                         detail="Solo se puede finalizar un trabajo aceptado.")
    try:
        cursor.execute(
            "UPDATE Trabajos SET estado = 'finalizado_por_prestador', fecha_finalizacion_prestador = GETDATE() WHERE id_trabajo = ?",
            id_trabajo)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error en la BBDD: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Trabajo marcado como finalizado. Esperando confirmación del cliente."}


@app.post("/trabajos/{id_trabajo}/confirmar", tags=["Trabajos"])
def confirm_trabajo_by_cliente(id_trabajo: int, current_user: UserInDB = Depends(get_current_active_user),
                               conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Trabajos WHERE id_trabajo = ?", id_trabajo)
    trabajo = cursor.fetchone()
    if not trabajo: raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if current_user.id_usuario != trabajo.id_cliente: raise HTTPException(status_code=403,
                                                                          detail="Solo el cliente puede confirmar el trabajo.")
    if trabajo.estado != 'finalizado_por_prestador': raise HTTPException(status_code=400,
                                                                         detail="El trabajo aún no ha sido marcado como finalizado por el prestador.")
    try:
        cursor.execute(
            "UPDATE Trabajos SET estado = 'completado', fecha_finalizacion_cliente = GETDATE() WHERE id_trabajo = ?",
            id_trabajo)
        cursor.execute("UPDATE Usuarios SET trabajos_realizados = trabajos_realizados + 1 WHERE id_usuario = ?",
                       trabajo.id_prestador)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error en la BBDD: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Trabajo completado. Ahora ambas partes pueden dejar una valoración."}


@app.post("/trabajos/{id_trabajo}/valorar", tags=["Trabajos"])
def valorar_trabajo(id_trabajo: int, valoracion: ValoracionTrabajoCreate,
                    current_user: UserInDB = Depends(get_current_active_user),
                    conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Trabajos WHERE id_trabajo = ?", id_trabajo)
    trabajo = cursor.fetchone()
    if not trabajo: raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if trabajo.estado != 'completado': raise HTTPException(status_code=400,
                                                           detail="Solo se pueden valorar trabajos completados.")
    if current_user.id_usuario not in [trabajo.id_cliente, trabajo.id_prestador]: raise HTTPException(status_code=403,
                                                                                                      detail="No participas en este trabajo.")

    id_autor = current_user.id_usuario
    rol_autor = 'cliente' if id_autor == trabajo.id_cliente else 'prestador'
    id_evaluado = trabajo.id_prestador if rol_autor == 'cliente' else trabajo.id_cliente
    try:
        cursor.execute("SELECT id_valoracion FROM Valoraciones WHERE id_trabajo = ? AND id_autor = ?", id_trabajo,
                       id_autor)
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Ya has enviado una valoración para este trabajo.")
        cursor.execute(
            "INSERT INTO Valoraciones (id_trabajo, id_autor, id_evaluado, rol_autor, puntaje, comentario) VALUES (?, ?, ?, ?, ?, ?)",
            id_trabajo, id_autor, id_evaluado, rol_autor, valoracion.puntaje, valoracion.comentario)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error en la BBDD: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Valoración enviada exitosamente."}


@app.get("/prestadores/{id_prestador}/trabajos", response_model=List[TrabajoHistorial], tags=["Prestadores"])
def get_prestador_trabajos_historial(id_prestador: int, conn: pyodbc.Connection = Depends(get_db_connection)):
    """
    Obtiene el historial de trabajos completados de un prestador,
    incluyendo la valoración del cliente para cada trabajo.
    """
    cursor = conn.cursor()
    query = """
        SELECT
            t.id_trabajo,
            t.descripcion,
            t.precio_acordado,
            t.fecha_finalizacion_cliente,
            v.puntaje AS puntaje_recibido,
            v.comentario AS comentario_recibido
        FROM Trabajos t
        LEFT JOIN Valoraciones v ON t.id_trabajo = v.id_trabajo AND v.rol_autor = 'cliente'
        WHERE t.id_prestador = ? AND t.estado = 'completado'
        ORDER BY t.fecha_finalizacion_cliente DESC;
    """
    try:
        cursor.execute(query, id_prestador)
        trabajos_db = cursor.fetchall()

        historial = [
            TrabajoHistorial(**dict(zip([column[0] for column in row.cursor_description], row)))
            for row in trabajos_db
        ]
        return historial
    except pyodbc.Error as e:
        raise HTTPException(status_code=500, detail=f"Error en la base de datos: {e}")
    finally:
        cursor.close()