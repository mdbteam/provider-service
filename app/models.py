# app/models.py
from pydantic import BaseModel, Field
from typing import List, Optional
from fastapi import Form, UploadFile, File
from datetime import date

class PrestadorResumen(BaseModel):
    id: str
    nombres: str
    primer_apellido: str
    foto_url: str
    oficios: List[str]
    resumen: Optional[str]
    puntuacion: float

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

class ValoracionCreate(BaseModel):
    puntaje: int = Field(..., ge=1, le=5)
    comentario: Optional[str] = None

# Modelo para el endpoint GET /profile/me
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

# Modelo interno para manejar el usuario autenticado
class UserInDB(BaseModel):
    id_usuario: int
    nombres: str
    primer_apellido: str
    correo: str
    id_rol: int
    estado: str