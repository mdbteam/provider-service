# provider-service/app/models.py
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
from fastapi import Form, UploadFile, File
from datetime import date, datetime

# --- CONFIGURACIÓN COMPARTIDA (Para Pydantic V2) ---
# Usamos esto para que los modelos puedan leer datos directo de los objetos row de pyodbc/SQLAlchemy
class DBModel(BaseModel):
    class Config:
        from_attributes = True  # Reemplaza a 'orm_mode = True' en Pydantic V2

# --- MODELOS GENERALES Y DE USUARIO ---

class UserInDB(DBModel):
    id_usuario: int
    nombres: str
    primer_apellido: str
    segundo_apellido: Optional[str] = None
    rut: str
    correo: str
    direccion: Optional[str] = None
    id_rol: int
    estado: str
    foto_url: str
    genero: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    telefono: Optional[str] = None

class UserPublic(DBModel):
    id: str
    nombres: str
    primer_apellido: str
    segundo_apellido: Optional[str] = None
    rut: str
    correo: str
    direccion: Optional[str] = None
    rol: str
    foto_url: str
    genero: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    telefono: Optional[str] = None

class PrestadorResumen(DBModel):
    id: Optional[str] = None
    id_usuario: Optional[int] = None
    nombres: str
    primer_apellido: str
    foto_url: Optional[str] = None
    oficios: List[str]
    puntuacion_promedio: float
    resumen: Optional[str] = None
    trabajos_realizados: Optional[int] = None
    genero: Optional[str] = None
    fecha_nacimiento: Optional[date] = None


class PrestadorStatusUpdate(BaseModel):
    estado: str = Field(..., description="Nuevo estado: 'activo' o 'suspendido'")

# --- MODELOS DE PERFIL DETALLADO ---

class ProfileUpdate(BaseModel):
    nombres: Optional[str] = Field(None, max_length=100)
    primer_apellido: Optional[str] = Field(None, max_length=100)
    segundo_apellido: Optional[str] = Field(None, max_length=100)
    direccion: Optional[str] = Field(None, max_length=255)
    genero: Optional[str] = Field(None, max_length=50)
    fecha_nacimiento: Optional[date] = None
    biografia: Optional[str] = None
    resumen_profesional: Optional[str] = None
    anos_experiencia: Optional[int] = None
    correo: Optional[str] = Field(None, max_length=100)
    telefono: Optional[str] = Field(None, max_length=15)

class ProfileDetail(DBModel):
    id_usuario: int
    nombres: str
    primer_apellido: str
    foto_url: str
    genero: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    biografia: Optional[str] = None
    resumen_profesional: Optional[str] = None
    anos_experiencia: Optional[int] = None

class ExperienciaCreate(BaseModel):
    cargo: str = Field(..., max_length=255)
    descripcion: str
    fecha_inicio: date
    fecha_fin: Optional[date] = None

class ExperienciaResponse(DBModel):
    id_experiencia: int
    id_usuario: int
    cargo: str
    descripcion: str
    fecha_inicio: date
    fecha_fin: Optional[date] = None

class ResenaPublica(DBModel):
    """Modelo simple para listas resumidas"""
    id_valoracion: int
    id_autor: int
    id_evaluado: int
    rol_autor: str
    puntaje: Optional[int] = None
    comentario: Optional[str] = None
    fecha_creacion: datetime

class PrestadorPublicoDetalle(DBModel):
    id_usuario: int
    nombres: str
    primer_apellido: str
    segundo_apellido: Optional[str] = None
    foto_url: str
    oficios: List[str]
    puntuacion_promedio: float
    trabajos_realizados: int
    perfil: Optional[ProfileDetail] = None
    portafolio: List[str]
    experiencia: List[ExperienciaResponse]
    resenas: List[ResenaPublica]

# --- MODELOS DE POSTULACIÓN ---

class PostulacionForm:
    def __init__(
        self,
        nombres: str = Form(...),
        primer_apellido: str = Form(...),
        segundo_apellido: str = Form(None),
        direccion: str = Form(...),
        telefono: str = Form(None),
        oficio: str = Form(...),
        bio: str = Form(...),
        archivos_portafolio: List[UploadFile] = File(...),
        archivos_certificados: List[UploadFile] = File(...)
    ):
        self.nombres = nombres
        self.primer_apellido = primer_apellido
        self.segundo_apellido = segundo_apellido
        self.direccion = direccion
        self.telefono = telefono
        self.oficio = oficio
        self.bio = bio
        self.archivos_portafolio = archivos_portafolio
        self.archivos_certificados = archivos_certificados

class PostulacionResponse(BaseModel):
    mensaje: str
    statusPostulacion: str

class PostulacionPendiente(DBModel):
    id_postulacion: int
    id_usuario: int
    nombres: str
    primer_apellido: str
    correo: str
    fecha_postulacion: datetime
    estado: str

# Modelo NUEVO para el detalle completo
class DetallePostulacion(DBModel):
    id_postulacion: int
    id_usuario: int
    nombres: str
    primer_apellido: str
    segundo_apellido: Optional[str] = None
    correo: str # O puedes usar EmailStr si tienes pydantic[email] instalado
    telefono: str
    direccion: str
    fecha_postulacion: datetime
    estado: str
    oficio: str
    bio: str
    archivos_portafolio: List[str]
    archivos_certificados: List[str]

class PostulacionModificar(BaseModel):
    notas_admin: str

class PostulacionRechazarBody(BaseModel):
    motivo_rechazo: Optional[str] = Field(None, max_length=500, description="Razón por la que se rechaza la postulación.")

# --- MODELOS DE TRABAJOS (CONTRATOS) ---

class TrabajoCreate(BaseModel):
    id_cita: int
    id_cliente: int
    id_prestador: int
    descripcion: str
    condiciones: Optional[str] = None
    precio_acordado: float

class TrabajoDetail(DBModel):
    id_trabajo: int
    id_cita: int
    id_cliente: int
    id_prestador: int
    descripcion: str
    condiciones: Optional[str] = None
    precio_acordado: float
    estado: str
    fecha_propuesta: datetime
    fecha_aceptacion: Optional[datetime] = None
    fecha_finalizacion_prestador: Optional[datetime] = None
    fecha_finalizacion_cliente: Optional[datetime] = None

class TrabajoHistorial(DBModel):
    id_trabajo: int
    descripcion: str
    precio_acordado: float
    fecha_finalizacion_cliente: datetime
    puntaje_recibido: Optional[int] = None
    comentario_recibido: Optional[str] = None

class ValoracionTrabajoCreate(BaseModel):
    puntaje: int = Field(..., ge=1, le=5)
    comentario: Optional[str] = None

# --- NUEVOS MODELOS DE VALORACIÓN (INTEGRADOS AQUÍ) ---

class ValoracionCreatedResponse(BaseModel):
    mensaje: str = "Valoración creada con éxito"
    id_valoracion: int
    nuevo_promedio_prestador: float

class AutorResumen(DBModel):
    """Resumen del autor de una reseña (para mostrar nombre y foto)"""
    id: int
    nombres: str
    primer_apellido: str
    foto_url: Optional[str] = None

class ResenaPublicaDetalle(DBModel):
    """Modelo detallado para la lista paginada de reseñas"""
    id_valoracion: int
    id_trabajo: int
    puntaje: int
    comentario: Optional[str]
    fecha_creacion: datetime
    autor: AutorResumen

class ResenaMiPerfil(DBModel):
    """Modelo para 'Mis Reseñas'"""
    id_valoracion: int
    puntaje: int
    comentario: Optional[str]
    fecha_creacion: datetime
    rol_autor: str
    autor_nombres: str
    evaluado_nombres: str

class MisResenasResponse(BaseModel):
    promedio_general: Optional[float] = None
    total_resenas: int
    resenas: List[ResenaMiPerfil]