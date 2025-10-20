# app/models.py
from pydantic import BaseModel
from typing import List, Optional
from fastapi import Form, UploadFile, File


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
            # Datos de Identificación
            nombres: str = Form(...),
            primer_apellido: str = Form(...),
            segundo_apellido: str = Form(None),
            direccion: str = Form(...),
            telefono: str = Form(None),

            # Perfil Profesional
            oficio: str = Form(...),
            bio: str = Form(...),

            # Documentación
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


# Modelo interno para manejar el usuario autenticado
class UserInDB(BaseModel):
    id_usuario: int
    nombres: str
    primer_apellido: str
    correo: str
    id_rol: int
    estado: str