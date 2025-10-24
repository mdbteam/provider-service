# provider-service/app/models.py
from pydantic import BaseModel, Field
from typing import List, Optional
from fastapi import Form, UploadFile, File
from datetime import date, datetime

# --- MODELOS GENERALES ---
class PrestadorResumen(BaseModel):
    id: str
    nombres: str
    primer_apellido: str
    foto_url: str
    oficios: List[str]
    resumen: Optional[str]
    puntuacion: float

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

class ProfileDetail(BaseModel): # Mantenido para vistas públicas detalladas si es necesario
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

# --- MODELO PARA ACTUALIZACIÓN DE PERFIL ---
class ProfileUpdate(BaseModel):
    direccion: Optional[str] = Field(None, max_length=255)
    biografia: Optional[str] = None
    correo: Optional[str] = Field(None, max_length=100) # Permitimos actualizar correo

# --- MODELOS PARA EXPERIENCIA LABORAL ---
class ExperienciaCreate(BaseModel):
    cargo: str = Field(..., max_length=255)
    descripcion: str
    fecha_inicio: date
    fecha_fin: Optional[date] = None # None si es actual

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
        telefono: str = Form(None), # Asume 'telefono' column exists in Usuarios
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