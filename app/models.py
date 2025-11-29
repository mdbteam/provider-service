# provider-service/app/models.py
from pydantic import BaseModel, Field
from typing import List, Optional
from fastapi import Form, UploadFile, File
from datetime import date, datetime

# --- MODELOS GENERALES ---
class PrestadorResumen(BaseModel):
    id: Optional[str] = None
    id_usuario: Optional[int] = None  # Si lo usas para debug
    nombres: str
    primer_apellido: str
    foto_url: Optional[str] = None
    oficios: List[str]
    puntuacion_promedio: float
    resumen: Optional[str] = None
    trabajos_realizados: Optional[int] = None  # Añadir
    genero: Optional[str] = None  # Añadir
    fecha_nacimiento: Optional[date] = None  # Añadir

class PostulacionRechazarBody(BaseModel):
    motivo: str = Field(..., min_length=10, description="Motivo del rechazo.")

class PostulacionModificarBody(BaseModel):
    estado: str = Field(..., description="Nuevo estado, ej: 'requiere_modificacion'")
    comentario: str = Field(..., description="Comentario para el usuario.")

class ResenaPublicaHistorial(BaseModel):
    id_trabajo: int
    id_valoracion: int
    fecha_creacion: datetime
    descripcion_cliente: str # Nombre del cliente que hizo la reseña
    puntaje: int
    comentario: Optional[str]

class TrabajoDetalleCliente(BaseModel):
    id_trabajo: int
    id_cita: int
    descripcion: Optional[str]
    condiciones: Optional[str]
    precio_acordado: Optional[float]
    estado: str
    prestador_nombres: str
# --- MODELO UserPublic UNIFICADO ---
class UserPublic(BaseModel):
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

# --- ORDEN CORREGIDO ---
# ProfileDetail DEBE definirse ANTES de PrestadorPublicoDetalle
class ProfileDetail(BaseModel):
    id_usuario: int
    nombres: str
    primer_apellido: str
    foto_url: str
    genero: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    biografia: Optional[str] = None
    resumen_profesional: Optional[str] = None
    anos_experiencia: Optional[int] = None

# --- MODELO UserInDB para provider-service ---
class UserInDB(BaseModel):
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

# --- MODELO PARA ACTUALIZACIÓN DE PERFIL (Req 2.2) ---
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

# --- MODELOS PARA EXPERIENCIA LABORAL ---
class ExperienciaCreate(BaseModel):
    cargo: str = Field(..., max_length=255)
    descripcion: str
    fecha_inicio: date
    fecha_fin: Optional[date] = None

class ExperienciaResponse(BaseModel):
    id_experiencia: int
    id_usuario: int
    cargo: str
    descripcion: str
    fecha_inicio: date
    fecha_fin: Optional[date] = None

# --- MODELOS PARA EL FLUJO DE POSTULACIÓN ---
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

class PostulacionPendiente(BaseModel):
    id_postulacion: int
    id_usuario: int
    nombres: str
    primer_apellido: str
    correo: str
    fecha_postulacion: datetime
    estado: str

class PostulacionModificar(BaseModel):
    notas_admin: str

class PostulacionRechazarBody(BaseModel):
    motivo_rechazo: Optional[str] = Field(None, max_length=500, description="Razón por la que se rechaza la postulación.")

class ResenaPublica(BaseModel):
    id_valoracion: int
    id_autor: int
    id_evaluado: int
    rol_autor: str
    puntaje: Optional[int] = None
    comentario: Optional[str] = None
    fecha_creacion: datetime

# --- MODELO PARA EL PERFIL PÚBLICO DETALLADO ---
class PrestadorPublicoDetalle(BaseModel):
    id_usuario: int
    nombres: str
    primer_apellido: str
    segundo_apellido: Optional[str] = None
    foto_url: str
    oficios: List[str]
    puntuacion_promedio: float
    trabajos_realizados: int
    perfil: Optional[ProfileDetail] = None # Ahora 'ProfileDetail' ya existe
    portafolio: List[str]
    experiencia: List[ExperienciaResponse]
    resenas: List[ResenaPublica]

# --- MODELOS PARA EL FLUJO DE TRABAJOS (CONTRATOS) ---
class TrabajoCreate(BaseModel):
    id_cita: int
    id_cliente: int
    id_prestador: int
    descripcion: str
    condiciones: Optional[str] = None
    precio_acordado: float

class TrabajoDetail(BaseModel):
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

class ValoracionTrabajoCreate(BaseModel):
    puntaje: int = Field(..., ge=1, le=5)
    comentario: Optional[str] = None

class TrabajoHistorial(BaseModel):
    id_trabajo: int
    descripcion: str
    precio_acordado: float
    fecha_finalizacion_cliente: datetime
    puntaje_recibido: Optional[int] = None
    comentario_recibido: Optional[str] = None