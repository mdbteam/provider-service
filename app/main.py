# app/main.py
from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile
from typing import List
import pyodbc
from dotenv import load_dotenv

load_dotenv()

from app.database import get_db_connection
from app.models import PrestadorResumen, PostulacionForm, PostulacionResponse, UserInDB, ProfileDetail, ValoracionCreate
from app.auth_utils import get_current_active_user, get_current_admin_user
from app.storage import upload_file_and_get_url

app = FastAPI(
    title="Servicio de Prestadores - Chambee",
    description="Gestiona los perfiles y postulaciones de los prestadores.",
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
        LEFT JOIN Valoraciones v ON u.id_usuario = v.id_prestador
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
def get_my_profile(
        current_user: UserInDB = Depends(get_current_active_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
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
def update_profile_picture(
        file: UploadFile = File(...),
        current_user: UserInDB = Depends(get_current_active_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    user_id = current_user.id_usuario
    photo_url = upload_file_and_get_url(file, user_id, "perfil")
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE Usuarios SET foto_url = ? WHERE id_usuario = ?", photo_url, user_id)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar la foto de perfil: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Foto de perfil actualizada exitosamente", "foto_url": photo_url}


@app.post("/postulaciones", response_model=PostulacionResponse, tags=["Postulaciones"])
def send_postulacion(
        form: PostulacionForm = Depends(),
        current_user: UserInDB = Depends(get_current_active_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    cursor = conn.cursor()
    user_id = current_user.id_usuario
    try:
        cursor.execute(
            "UPDATE Usuarios SET nombres = ?, primer_apellido = ?, segundo_apellido = ?, direccion = ? WHERE id_usuario = ?",
            form.nombres, form.primer_apellido, form.segundo_apellido, form.direccion, user_id
        )
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
            user_id, form.bio, form.oficio, user_id, form.bio, form.oficio
        )

        oficios = [o.strip() for o in form.oficio.split(',')]
        for oficio_nombre in oficios:
            if oficio_nombre:
                cursor.execute("INSERT INTO Oficio (id_usuario, nombre_oficio) VALUES (?, ?)", user_id, oficio_nombre)

        cursor.execute("INSERT INTO Postulaciones (id_usuario, estado) VALUES (?, ?)", user_id, STATUS_PENDIENTE)
        cursor.execute("UPDATE Usuarios SET estado = ? WHERE id_usuario = ?", STATUS_PENDIENTE, user_id)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error en la base de datos: {e}")
    finally:
        cursor.close()
    return PostulacionResponse(mensaje="Postulación enviada exitosamente.", statusPostulacion=STATUS_PENDIENTE)


@app.post("/admin/postulaciones/{id_postulacion}/aprobar", tags=["Administración"])
def approve_postulacion(
        id_postulacion: int,
        admin_user: UserInDB = Depends(get_current_admin_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT p.id_usuario, u.id_rol FROM Postulaciones p JOIN Usuarios u ON p.id_usuario = u.id_usuario "
            "WHERE p.id_postulacion = ? AND p.estado = ?",
            id_postulacion, STATUS_PENDIENTE
        )
        postulacion = cursor.fetchone()
        if not postulacion:
            raise HTTPException(status_code=404, detail="Postulación no encontrada o ya procesada.")

        id_usuario, rol_actual = postulacion.id_usuario, postulacion.id_rol
        nuevo_rol = ROLE_HYBRID if rol_actual == ROLE_CLIENTE else rol_actual

        cursor.execute("UPDATE Usuarios SET estado = ?, id_rol = ? WHERE id_usuario = ?", STATUS_ACTIVO, nuevo_rol,
                       id_usuario)
        cursor.execute("UPDATE Postulaciones SET estado = 'aprobada' WHERE id_postulacion = ?", id_postulacion)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al aprobar: {e}")
    finally:
        cursor.close()
    return {"mensaje": f"Postulación {id_postulacion} aprobada. El usuario {id_usuario} ahora es prestador."}


@app.post("/prestadores/{id_prestador}/valorar", tags=["Prestadores"])
def create_valoracion(
        id_prestador: int,
        valoracion_data: ValoracionCreate,
        current_user: UserInDB = Depends(get_current_active_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    id_cliente = current_user.id_usuario
    if id_cliente == id_prestador:
        raise HTTPException(status_code=400, detail="No puedes valorarte a ti mismo.")
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO Valoraciones (id_prestador, id_cliente, puntaje, comentario) VALUES (?, ?, ?, ?)",
            id_prestador, id_cliente, valoracion_data.puntaje, valoracion_data.comentario
        )
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error en la base de datos: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Valoración enviada exitosamente."}