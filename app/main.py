# provider-service/app/main.py
from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Query, Response  # <--- MODIFICADO
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
import pyodbc
from dotenv import load_dotenv
from datetime import date

load_dotenv(override=True)

from app.database import get_db_connection
# Importamos todos los modelos necesarios
from app.models import (
    PrestadorResumen, UserInDB, ProfileDetail, PostulacionForm, PostulacionResponse,
    TrabajoCreate, TrabajoDetail, ValoracionTrabajoCreate, TrabajoHistorial, UserPublic,
    ProfileUpdate, ExperienciaCreate, ExperienciaResponse, ResenaPublica,
    PrestadorPublicoDetalle, PostulacionPendiente,
    # --- (NUEVOS MODELOS) ---
    PostulacionRechazarBody, PostulacionModificarBody, ResenaPublicaHistorial, TrabajoDetalleCliente  # <--- NUEVO
)
from app.auth_utils import get_current_active_user, get_current_admin_user
from app.storage import upload_file_and_get_url

app = FastAPI(
    title="Servicio de Prestadores - Chambee",
    description="Gestiona perfiles, postulaciones y trabajos de los prestadores.",
    version="1.0.0"
)

# --- CONFIGURACIÓN CORS ---
origins = [
    "http://localhost",
    "http://localhost:8081",
    "https://auth-service-1-8301.onrender.com",
    "*",  # solo para desarrollo
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,             # Permite enviar credenciales (cookies, auth headers)
    allow_methods=["*"],                # Permite todos los métodos HTTP
    allow_headers=["*"],                # Permite todas las cabeceras
)
# --- CONFIGURACIÓN CORS ---
# Constantes
ROLE_PROVEEDOR = 2;
ROLE_HYBRID = 3;
ROLE_CLIENTE = 1
STATUS_ACTIVO = 'activo';
STATUS_PENDIENTE = 'pendiente'


def es_prestador(user: UserInDB):
    if user.id_rol not in [ROLE_PROVEEDOR, ROLE_HYBRID]:
        raise HTTPException(status_code=403, detail="Acción solo para prestadores.")


@app.get("/", tags=["Status"])
def root():
    return {"message": "Provider Service funcionando 🚀"}


# --- ENDPOINTS DE VISUALIZACIÓN ---

@app.get("/prestadores", response_model=List[PrestadorResumen], tags=["Prestadores"])
def get_all_prestadores(
        q: Optional[str] = None,
        oficio: Optional[str] = None,  # <--- NUEVO (reemplaza 'categoria')
        rating_min: Optional[float] = Query(None, ge=0, le=5),  # <--- NUEVO
        sort_by: Optional[str] = None,  # <--- NUEVO
        limit: Optional[int] = Query(None, gt=0),  # <--- NUEVO
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    cursor = conn.cursor()

    params = [ROLE_PROVEEDOR, ROLE_HYBRID]

    # Usamos un CTE (Common Table Expression) para calcular estadísticas
    # y luego filtrar sobre ellas. Es mucho más limpio.
    query = """
        WITH PrestadorStats AS (
            SELECT 
                u.id_usuario, u.nombres, u.primer_apellido, u.foto_url,
                (SELECT STRING_AGG(o.nombre_oficio, ', ') FROM Oficio o WHERE o.id_usuario = u.id_usuario) AS oficios_str,
                ISNULL((SELECT AVG(CAST(v.puntaje AS FLOAT)) 
                        FROM Valoraciones v 
                        WHERE v.id_evaluado = u.id_usuario AND v.rol_autor = 'cliente'), 0) AS puntuacion_promedio,
                ISNULL((SELECT COUNT(t.id_trabajo) 
                        FROM Trabajos t 
                        WHERE t.id_prestador = u.id_usuario AND t.estado = 'completado'), 0) AS trabajos_realizados
            FROM Usuarios u
            WHERE u.id_rol IN (?, ?) AND u.estado = 'activo'
        )
        SELECT *
        FROM PrestadorStats
        WHERE 1=1
    """

    # Añadir filtro de OFICIO
    if oficio:
        query += " AND oficios_str LIKE ?"
        params.append(f"%{oficio}%")

    # Añadir filtro de RATING MÍNIMO
    if rating_min is not None:
        query += " AND puntuacion_promedio >= ?"
        params.append(rating_min)

    # Añadir filtro de BÚSQUEDA (q)
    if q:
        query += " AND (nombres LIKE ? OR primer_apellido LIKE ? OR oficios_str LIKE ?)"
        search_term = f"%{q}%"
        params.extend([search_term, search_term, search_term])

    # Ordenamiento
    if sort_by == 'rating_desc':
        query += " ORDER BY puntuacion_promedio DESC"
    else:
        # Orden por defecto (se puede cambiar)
        query += " ORDER BY nombres ASC"

    # Límite (Usando OFFSET/FETCH para compatibilidad con parámetros)
    if limit is not None:
        query += " OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY"
        params.append(limit)

    try:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        prestadores = [PrestadorResumen(
            id_usuario=row.id_usuario,
            nombres=row.nombres,
            primer_apellido=row.primer_apellido,
            foto_url=row.foto_url,
            oficios=row.oficios_str.split(', ') if row.oficios_str else [],
            puntuacion_promedio=round(row.puntuacion_promedio, 1),
            trabajos_realizados=row.trabajos_realizados
        ) for row in rows]
        return prestadores

    except pyodbc.Error as e:
        raise HTTPException(status_code=500, detail=f"Error en la base de datos: {e}")
    finally:
        cursor.close()


@app.get("/categorias", response_model=List[str], tags=["Prestadores"])
def get_categorias():
    """(Req 2.4) Devuelve la lista de oficios únicos para filtros."""
    categorias_fijas = [
        "Gasfitería", "Electricidad", "Pintura", "Albañilería", "Carpintería",
        "Jardinería", "Mecánica", "Plomería", "Cerrajería",
        "Reparación de Electrodomésticos", "Instalación de Aire Acondicionado",
        "Servicios de Limpieza", "Techado", "Otro"
    ]
    return categorias_fijas


@app.get("/prestadores/{id_prestador}", response_model=PrestadorPublicoDetalle, tags=["Prestadores"])
def get_prestador_detalle(id_prestador: int, conn: pyodbc.Connection = Depends(get_db_connection)):
    """(Req 2.5) Obtiene el perfil público detallado de un prestador."""
    cursor = conn.cursor()
    try:
        # 1. Datos principales
        cursor.execute("""
            SELECT u.*, p.biografia, p.resumen_profesional, p.anos_experiencia,
                   ISNULL((SELECT AVG(CAST(v.puntaje AS FLOAT)) FROM Valoraciones v WHERE v.id_evaluado = u.id_usuario AND v.rol_autor = 'cliente'), 0) AS puntuacion_promedio,
                   ISNULL((SELECT COUNT(t.id_trabajo) FROM Trabajos t WHERE t.id_prestador = u.id_usuario AND t.estado = 'completado'), 0) AS trabajos_realizados_calc
            FROM Usuarios u
            LEFT JOIN Perfil p ON u.id_usuario = p.id_usuario
            WHERE u.id_usuario = ? AND u.id_rol IN (?, ?) AND u.estado = 'activo'
        """, id_prestador, ROLE_PROVEEDOR, ROLE_HYBRID)
        prestador = cursor.fetchone()
        if not prestador: raise HTTPException(status_code=404, detail="Prestador no encontrado.")

        # 2. Oficios
        cursor.execute("SELECT nombre_oficio FROM Oficio WHERE id_usuario = ?", id_prestador)
        oficios = [row.nombre_oficio for row in cursor.fetchall()]

        # 3. Portafolio (URLs)
        cursor.execute("SELECT enlace_imagen FROM Portafolio WHERE id_usuario = ?", id_prestador)
        portafolio_urls = [row.enlace_imagen for row in cursor.fetchall()]

        # 4. Experiencia
        cursor.execute("SELECT * FROM ExperienciaLaboral WHERE id_usuario = ? ORDER BY fecha_inicio DESC", id_prestador)
        experiencia = [ExperienciaResponse(**dict(zip([col[0] for col in row.cursor_description], row))) for row in
                       cursor.fetchall()]

        # 5. Reseñas
        cursor.execute(
            "SELECT v.*, (u.nombres + ' ' + u.primer_apellido) as nombre_autor FROM Valoraciones v LEFT JOIN Usuarios u ON v.id_autor = u.id_usuario WHERE v.id_evaluado = ? AND v.rol_autor = 'cliente' ORDER BY v.fecha_creacion DESC",
            id_prestador)  # <--- MODIFICADO (para incluir nombre autor)
        resenas = [ResenaPublica(**dict(zip([col[0] for col in row.cursor_description], row))) for row in
                   cursor.fetchall()]

        perfil_data = ProfileDetail(
            id_usuario=prestador.id_usuario, nombres=prestador.nombres, primer_apellido=prestador.primer_apellido,
            foto_url=prestador.foto_url, genero=prestador.genero, fecha_nacimiento=prestador.fecha_nacimiento,
            biografia=prestador.biografia, resumen_profesional=prestador.resumen_profesional,
            anos_experiencia=prestador.anos_experiencia
        )

        return PrestadorPublicoDetalle(
            id_usuario=prestador.id_usuario, nombres=prestador.nombres, primer_apellido=prestador.primer_apellido,
            segundo_apellido=prestador.segundo_apellido, foto_url=prestador.foto_url, oficios=oficios,
            puntuacion_promedio=round(prestador.puntuacion_promedio, 1),
            trabajos_realizados=prestador.trabajos_realizados_calc,  # <--- MODIFICADO
            perfil=perfil_data, portafolio=portafolio_urls, experiencia=experiencia, resenas=resenas
        )
    except pyodbc.Error as e:
        raise HTTPException(status_code=500, detail=f"Error BBDD: {e}")
    finally:
        cursor.close()


# --- ENDPOINTS DE PERFIL ---

@app.get("/profile/me", response_model=UserPublic, tags=["Perfil"])
def read_users_me(current_user: UserInDB = Depends(get_current_active_user)):
    # (Sin cambios)
    rol_map = {0: "administrador", 1: "cliente", 2: "prestador", 3: "híbrido"}
    rol_str = rol_map.get(current_user.id_rol, "desconocido")
    return UserPublic(
        id=str(current_user.id_usuario), nombres=current_user.nombres, primer_apellido=current_user.primer_apellido,
        segundo_apellido=current_user.segundo_apellido, rut=current_user.rut, correo=current_user.correo,
        direccion=current_user.direccion, rol=rol_str, foto_url=current_user.foto_url,
        genero=current_user.genero, fecha_nacimiento=current_user.fecha_nacimiento, telefono=current_user.telefono
    )


@app.put("/profile/me/picture", response_model=UserPublic, tags=["Perfil"])
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
    return read_users_me(current_user=current_user)


@app.patch("/profile/me", response_model=UserPublic, tags=["Perfil"])
def update_my_profile(
        profile_data: ProfileUpdate,
        current_user: UserInDB = Depends(get_current_active_user),
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    user_id = current_user.id_usuario
    cursor = conn.cursor()
    user_updates, user_values, perfil_updates, perfil_values, perfil_insert_cols, perfil_insert_placeholders = [], [], [], [], [], []

    # Validar Correo
    if profile_data.correo is not None and profile_data.correo != current_user.correo:
        cursor.execute("SELECT id_usuario FROM Usuarios WHERE correo = ? AND id_usuario != ?", profile_data.correo,
                       user_id)
        if cursor.fetchone():
            cursor.close();
            raise HTTPException(status_code=409, detail="El nuevo correo ya está en uso.")
        user_updates.append("correo = ?");
        user_values.append(profile_data.correo)

    # (Lógica de actualización parcial sin cambios)
    if profile_data.direccion is not None: user_updates.append("direccion = ?"); user_values.append(
        profile_data.direccion)
    if profile_data.nombres is not None: user_updates.append("nombres = ?"); user_values.append(profile_data.nombres)
    if profile_data.primer_apellido is not None: user_updates.append("primer_apellido = ?"); user_values.append(
        profile_data.primer_apellido)
    if profile_data.segundo_apellido is not None: user_updates.append("segundo_apellido = ?"); user_values.append(
        profile_data.segundo_apellido)
    if profile_data.genero is not None: user_updates.append("genero = ?"); user_values.append(profile_data.genero)
    if profile_data.fecha_nacimiento is not None: user_updates.append("fecha_nacimiento = ?"); user_values.append(
        profile_data.fecha_nacimiento)
    if profile_data.telefono is not None: user_updates.append("telefono = ?"); user_values.append(profile_data.telefono)

    if profile_data.biografia is not None:
        perfil_updates.append("biografia = ?");
        perfil_values.append(profile_data.biografia)
        perfil_insert_cols.append("biografia");
        perfil_insert_placeholders.append("?")
    if profile_data.resumen_profesional is not None:
        perfil_updates.append("resumen_profesional = ?");
        perfil_values.append(profile_data.resumen_profesional)
        perfil_insert_cols.append("resumen_profesional");
        perfil_insert_placeholders.append("?")
    if profile_data.anos_experiencia is not None:
        perfil_updates.append("anos_experiencia = ?");
        perfil_values.append(profile_data.anos_experiencia)
        perfil_insert_cols.append("anos_experiencia");
        perfil_insert_placeholders.append("?")
    if not user_updates and not perfil_updates:
        cursor.close();
        raise HTTPException(status_code=400, detail="No hay datos para actualizar.")
    try:
        if user_updates:
            cursor.execute(f"UPDATE Usuarios SET {', '.join(user_updates)} WHERE id_usuario = ?",
                           tuple(user_values + [user_id]))
        if perfil_updates:
            perfil_query = f"""MERGE Perfil AS target USING (SELECT ? AS id_usuario) AS source ON (target.id_usuario = source.id_usuario)
                           WHEN MATCHED THEN UPDATE SET {', '.join(perfil_updates)}
                           WHEN NOT MATCHED THEN INSERT (id_usuario, {', '.join(perfil_insert_cols)}) VALUES (?, {', '.join(perfil_insert_placeholders)});"""
            cursor.execute(perfil_query, tuple([user_id] + perfil_values + [user_id] + perfil_values))
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error BBDD: {e}")
    if cursor: cursor.close()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Usuarios WHERE id_usuario = ?", user_id)
    updated_user_record = cursor.fetchone()
    cursor.close()
    if not updated_user_record:
        raise HTTPException(status_code=404, detail="Usuario no encontrado después de actualizar.")
    rol_map = {0: "admin", 1: "cliente", 2: "prestador", 3: "híbrido"}
    rol_str = rol_map.get(updated_user_record.id_rol, "desconocido")
    user_data = dict(zip([col[0] for col in updated_user_record.cursor_description], updated_user_record))
    return UserPublic(
        id=str(user_data['id_usuario']),
        nombres=user_data['nombres'],
        primer_apellido=user_data['primer_apellido'],
        segundo_apellido=user_data['segundo_apellido'],
        rut=user_data['rut'],
        correo=user_data['correo'],
        direccion=user_data['direccion'],
        rol=rol_str,
        foto_url=user_data['foto_url'],
        genero=user_data['genero'],
        fecha_nacimiento=user_data['fecha_nacimiento'],
        telefono=user_data['telefono']
    )


@app.post("/profile/me/experience", response_model=ExperienciaResponse, status_code=status.HTTP_201_CREATED,
          tags=["Perfil"])
def add_experience(experience_data: ExperienciaCreate, current_user: UserInDB = Depends(get_current_active_user),
                   conn: pyodbc.Connection = Depends(get_db_connection)):
    es_prestador(current_user)
    user_id = current_user.id_usuario
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO ExperienciaLaboral (id_usuario, cargo, descripcion, fecha_inicio, fecha_fin) OUTPUT INSERTED.* VALUES (?, ?, ?, ?, ?)",
            user_id, experience_data.cargo, experience_data.descripcion, experience_data.fecha_inicio,
            experience_data.fecha_fin)
        new_experience = cursor.fetchone()
        conn.commit()
        exp_dict = dict(zip([column[0] for column in new_experience.cursor_description], new_experience))
        return ExperienciaResponse(**exp_dict)
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error BBDD: {e}")
    finally:
        cursor.close()


@app.get("/profile/me/experience", response_model=List[ExperienciaResponse], tags=["Perfil"])
def get_my_experience(current_user: UserInDB = Depends(get_current_active_user),
                      conn: pyodbc.Connection = Depends(get_db_connection)):
    user_id = current_user.id_usuario
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ExperienciaLaboral WHERE id_usuario = ? ORDER BY fecha_inicio DESC", user_id)
    experiences_db = cursor.fetchall()
    cursor.close()
    experiences = [ExperienciaResponse(**dict(zip([column[0] for column in row.cursor_description], row))) for row in
                   experiences_db]
    return experiences


@app.delete("/profile/me/experience/{id_experiencia}", status_code=status.HTTP_204_NO_CONTENT, tags=["Perfil"])
def delete_experience(id_experiencia: int, current_user: UserInDB = Depends(get_current_active_user),
                      conn: pyodbc.Connection = Depends(get_db_connection)):
    """(Req 1.10) (Prestador) Elimina un ítem de experiencia laboral de su propio perfil."""
    user_id = current_user.id_usuario
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM ExperienciaLaboral WHERE id_experiencia = ? AND id_usuario = ?",
            id_experiencia, user_id
        )

        # Si rowcount es 0, significa que no encontró la experiencia O no le pertenecía
        if cursor.rowcount == 0:
            conn.rollback()  # No es necesario, pero es buena práctica
            raise HTTPException(status_code=404, detail="Experiencia no encontrada o no pertenece al usuario.")

        conn.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error BBDD: {e}")
    finally:
        cursor.close()


@app.get("/prestadores/{id_prestador}/experience", response_model=List[ExperienciaResponse], tags=["Prestadores"])
def get_prestador_experience(id_prestador: int, conn: pyodbc.Connection = Depends(get_db_connection)):
    # (Sin cambios)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ExperienciaLaboral WHERE id_usuario = ? ORDER BY fecha_inicio DESC", id_prestador)
    experiences_db = cursor.fetchall()
    cursor.close()
    experiences = [ExperienciaResponse(**dict(zip([column[0] for column in row.cursor_description], row))) for row in
                   experiences_db]
    return experiences


# --- ENDPOINTS DE POSTULACIÓN ---
@app.post("/postulaciones", response_model=PostulacionResponse, tags=["Postulaciones"])
def send_postulacion(form: PostulacionForm = Depends(), current_user: UserInDB = Depends(get_current_active_user),
                     conn: pyodbc.Connection = Depends(get_db_connection)):
    # (Sin cambios)
    cursor = conn.cursor()
    user_id = current_user.id_usuario
    try:
        # (Lógica de postulación sin cambios)
        cursor.execute(
            "UPDATE Usuarios SET nombres = ?, primer_apellido = ?, segundo_apellido = ?, direccion = ?, telefono = ? WHERE id_usuario = ?",
            form.nombres, form.primer_apellido, form.segundo_apellido, form.direccion, form.telefono, user_id)
        cursor.execute("DELETE FROM Portafolio WHERE id_usuario = ?", user_id)
        cursor.execute("DELETE FROM Certificaciones WHERE id_usuario = ?", user_id)
        cursor.execute("DELETE FROM Oficio WHERE id_usuario = ?", user_id)
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
        cursor.execute(
            "MERGE Postulaciones AS target USING (SELECT ? as id_usuario) AS source ON (target.id_usuario = source.id_usuario) "
            "WHEN MATCHED THEN UPDATE SET estado = ?, fecha_postulacion = GETDATE(), notas_admin = NULL "  # <--- MODIFICADO (Limpiamos notas)
            "WHEN NOT MATCHED THEN INSERT (id_usuario, estado) VALUES (?, ?);",
            user_id, STATUS_PENDIENTE, user_id, STATUS_PENDIENTE)
        cursor.execute("UPDATE Usuarios SET estado = ? WHERE id_usuario = ?", STATUS_PENDIENTE, user_id)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error en BBDD Postulación: {e}")
    finally:
        cursor.close()
    return PostulacionResponse(mensaje="Postulación enviada exitosamente.", statusPostulacion=STATUS_PENDIENTE)


@app.get("/postulaciones/pendientes", response_model=List[PostulacionPendiente], tags=["Administración"])
def get_pendientes(admin_user: UserInDB = Depends(get_current_admin_user),
                   conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id_postulacion, u.id_usuario, u.nombres, u.primer_apellido, u.correo, p.fecha_postulacion, p.estado
        FROM Postulaciones p JOIN Usuarios u ON p.id_usuario = u.id_usuario
        WHERE p.estado = 'pendiente' ORDER BY p.fecha_postulacion ASC
    """)
    pendientes_db = cursor.fetchall()
    cursor.close()
    pendientes = [PostulacionPendiente(**dict(zip([column[0] for column in row.cursor_description], row))) for row in
                  pendientes_db]
    return pendientes


@app.post("/postulaciones/{id_postulacion}/aprobar", tags=["Administración"])
def approve_postulacion(id_postulacion: int, admin_user: UserInDB = Depends(get_current_admin_user),
                        conn: pyodbc.Connection = Depends(get_db_connection)):
    """(Req 1.5) Aprueba una postulación."""
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
        cursor.execute("UPDATE Postulaciones SET estado = 'aprobada', notas_admin = NULL WHERE id_postulacion = ?",
                       id_postulacion)  # <--- MODIFICADO (Limpiamos notas)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error al aprobar: {e}")
    finally:
        cursor.close()

    return {"status": "aprobada", "id_postulacion": id_postulacion}  # <--- MODIFICADO

@app.post("/postulaciones/{id_postulacion}/rechazar", tags=["Administración"])
def reject_postulacion(id_postulacion: int,
                       body: PostulacionRechazarBody,  # <--- NUEVO
                       admin_user: UserInDB = Depends(get_current_admin_user),
                       conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id_usuario FROM Postulaciones WHERE id_postulacion = ? AND estado = ?", id_postulacion,
                       STATUS_PENDIENTE)
        postulacion = cursor.fetchone()
        if not postulacion: raise HTTPException(status_code=404, detail="Postulación no encontrada o ya procesada.")

        id_usuario = postulacion.id_usuario
        cursor.execute("UPDATE Usuarios SET estado = ? WHERE id_usuario = ?", STATUS_ACTIVO,
                       id_usuario)  # Lo reactivamos como cliente

        # Guardamos el motivo del rechazo en 'notas_admin'
        cursor.execute("UPDATE Postulaciones SET estado = 'rechazada', notas_admin = ? WHERE id_postulacion = ?",
                       body.motivo, id_postulacion)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error al rechazar: {e}")
    finally:
        cursor.close()

    return {"status": "rechazada", "id_postulacion": id_postulacion}

@app.patch("/postulaciones/{id_postulacion}/modificar", tags=["Administración"])
def modify_postulacion(id_postulacion: int,
                       data: PostulacionModificarBody,
                       admin_user: UserInDB = Depends(get_current_admin_user),
                       conn: pyodbc.Connection = Depends(get_db_connection)):
    """(Req 1.7) Marca una postulación para que el usuario la corrija."""
    cursor = conn.cursor()

    # Verificamos que el estado sea el esperado
    if data.estado != "requiere_modificacion":
        raise HTTPException(status_code=400,
                            detail="El único estado permitido para esta acción es 'requiere_modificacion'")

    try:
        # Actualizamos el estado y el comentario (en notas_admin)
        cursor.execute(
            "UPDATE Postulaciones SET estado = ?, notas_admin = ? WHERE id_postulacion = ?",
            data.estado, data.comentario, id_postulacion
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Postulación no encontrada.")

        # También ponemos al usuario en estado 'pendiente' para que pueda editar
        cursor.execute(
            "UPDATE Usuarios SET estado = ? WHERE id_usuario = (SELECT id_usuario FROM Postulaciones WHERE id_postulacion = ?)",
            STATUS_PENDIENTE, id_postulacion
        )

        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error al modificar: {e}")
    finally:
        cursor.close()

    return {"status": data.estado, "id_postulacion": id_postulacion, "comentario": data.comentario}  # <--- MODIFICADO


# --- ENDPOINTS DE TRABAJOS (CONTRATOS) ---

@app.get("/trabajos/{id_trabajo}", response_model=TrabajoDetalleCliente, tags=["Trabajos"])
def get_trabajo_detalle(id_trabajo: int,
                        current_user: UserInDB = Depends(get_current_active_user),
                        conn: pyodbc.Connection = Depends(get_db_connection)):
    """(Req 3.1) Obtiene los detalles de un trabajo/propuesta."""
    cursor = conn.cursor()
    try:
        # Hacemos JOIN con Usuarios para obtener el nombre del prestador
        query = """
            SELECT 
                t.*, 
                (u.nombres + ' ' + u.primer_apellido) AS prestador_nombres
            FROM Trabajos t
            JOIN Usuarios u ON t.id_prestador = u.id_usuario
            WHERE t.id_trabajo = ?
        """
        cursor.execute(query, id_trabajo)
        trabajo = cursor.fetchone()

        if not trabajo:
            raise HTTPException(status_code=404, detail="Trabajo no encontrado.")

        # Verificación de seguridad: Solo el cliente o el prestador involucrados pueden ver
        if current_user.id_usuario not in [trabajo.id_cliente, trabajo.id_prestador]:
            raise HTTPException(status_code=403, detail="No tienes permiso para ver este trabajo.")

        # Mapeamos el resultado al modelo Pydantic
        trabajo_dict = dict(zip([column[0] for column in trabajo.cursor_description], trabajo))
        return TrabajoDetalleCliente(**trabajo_dict)

    except pyodbc.Error as e:
        raise HTTPException(status_code=500, detail=f"Error BBDD: {e}")
    finally:
        cursor.close()


@app.post("/trabajos", response_model=TrabajoDetail, status_code=status.HTTP_201_CREATED, tags=["Trabajos"])
def propose_trabajo(trabajo_data: TrabajoCreate, current_user: UserInDB = Depends(get_current_active_user),
                    conn: pyodbc.Connection = Depends(get_db_connection)):
    # (Sin cambios)
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
    # (Sin cambios)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Trabajos WHERE id_trabajo = ?", id_trabajo)
    trabajo = cursor.fetchone()
    if not trabajo: raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if current_user.id_usuario != trabajo.id_cliente: raise HTTPException(status_code=403,
                                                                          detail="Solo el cliente puede aceptar.")
    if trabajo.estado != 'propuesto': raise HTTPException(status_code=400, detail="Trabajo no puede ser aceptado.")
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
    # (Sin cambios)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Trabajos WHERE id_trabajo = ?", id_trabajo)
    trabajo = cursor.fetchone()
    if not trabajo: raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if current_user.id_usuario != trabajo.id_prestador: raise HTTPException(status_code=403,
                                                                            detail="Solo el prestador puede finalizar.")
    if trabajo.estado not in ['aceptado', 'en_progreso']: raise HTTPException(status_code=400,
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
    return {"mensaje": "Trabajo marcado como finalizado por prestador."}


@app.post("/trabajos/{id_trabajo}/confirmar", tags=["Trabajos"])
def confirm_trabajo_by_cliente(id_trabajo: int, current_user: UserInDB = Depends(get_current_active_user),
                               conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Trabajos WHERE id_trabajo = ?", id_trabajo)
    trabajo = cursor.fetchone()
    if not trabajo: raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if current_user.id_usuario != trabajo.id_cliente: raise HTTPException(status_code=403,
                                                                          detail="Solo el cliente puede confirmar.")
    if trabajo.estado != 'finalizado_por_prestador': raise HTTPException(status_code=400,
                                                                         detail="El prestador aún no ha finalizado.")
    try:
        cursor.execute(
            "UPDATE Trabajos SET estado = 'completado', fecha_finalizacion_cliente = GETDATE() WHERE id_trabajo = ?",
            id_trabajo)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error en la BBDD: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Trabajo completado. Ahora pueden valorarse."}


@app.post("/trabajos/{id_trabajo}/valorar", tags=["Trabajos"])
def valorar_trabajo(id_trabajo: int, valoracion: ValoracionTrabajoCreate,
                    current_user: UserInDB = Depends(get_current_active_user),
                    conn: pyodbc.Connection = Depends(get_db_connection)):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Trabajos WHERE id_trabajo = ?", id_trabajo)
    trabajo = cursor.fetchone()
    if not trabajo: raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if trabajo.estado != 'completado': raise HTTPException(status_code=400, detail="Solo trabajos completados.")
    if current_user.id_usuario not in [trabajo.id_cliente, trabajo.id_prestador]: raise HTTPException(status_code=403,
                                                                                                      detail="No participas.")
    id_autor = current_user.id_usuario
    rol_autor = 'cliente' if id_autor == trabajo.id_cliente else 'prestador'
    id_evaluado = trabajo.id_prestador if rol_autor == 'cliente' else trabajo.id_cliente
    try:
        cursor.execute("SELECT id_valoracion FROM Valoraciones WHERE id_trabajo = ? AND id_autor = ?", id_trabajo,
                       id_autor)
        if cursor.fetchone(): raise HTTPException(status_code=400, detail="Ya has valorado este trabajo.")
        cursor.execute(
            "INSERT INTO Valoraciones (id_trabajo, id_autor, id_evaluado, rol_autor, puntaje, comentario) VALUES (?, ?, ?, ?, ?, ?)",
            id_trabajo, id_autor, id_evaluado, rol_autor, valoracion.puntaje, valoracion.comentario)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback();
        raise HTTPException(status_code=500, detail=f"Error en la BBDD: {e}")
    finally:
        cursor.close()
    return {"mensaje": "Valoración enviada."}


@app.get("/prestadores/{id_prestador}/trabajos", response_model=List[ResenaPublicaHistorial],
         tags=["Prestadores"])  # <--- MODIFICADO
def get_prestador_trabajos_historial(id_prestador: int, conn: pyodbc.Connection = Depends(get_db_connection)):
    """(Req 1.9) Obtiene el historial público de trabajos/reseñas de un prestador."""
    cursor = conn.cursor()

    # Esta consulta ahora obtiene las VALORACIONES (reseñas) que recibió el prestador
    query = """
        SELECT 
            v.id_valoracion, 
            v.id_trabajo, 
            v.fecha_creacion, 
            (u_autor.nombres + ' ' + u_autor.primer_apellido) AS descripcion_cliente, 
            v.puntaje, 
            v.comentario
        FROM Valoraciones v
        JOIN Usuarios u_autor ON v.id_autor = u_autor.id_usuario
        WHERE v.id_evaluado = ? AND v.rol_autor = 'cliente'
        ORDER BY v.fecha_creacion DESC;
    """

    try:
        cursor.execute(query, id_prestador)
        reseñas_db = cursor.fetchall()

        historial = [ResenaPublicaHistorial(**dict(zip([column[0] for column in row.cursor_description], row))) for row
                     in
                     reseñas_db]
        return historial

    except pyodbc.Error as e:
        raise HTTPException(status_code=500, detail=f"Error BBDD: {e}")
    finally:
        cursor.close()