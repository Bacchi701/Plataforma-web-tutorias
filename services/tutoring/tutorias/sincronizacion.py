"""Sincronizacion de las copias de lectura de Tutorias (HU-19, AD-07).

usuario_ref copia de Identidad el nombre, el apellido, la carrera, la sede y
si la cuenta esta activa, y asignatura_ref copia de Catalogo la sigla y el
nombre. copias.py las pone al dia solo cuando el propio usuario hace algo en
Tutorias; sincronizar() lo hace para todos, sin token, en tres pasos:

1. usuarios (criterios 1 y 2, A-01): todas las filas de usuario_ref, de la
   mas antigua a la mas nueva, por lotes de TAMANO_LOTE ids, con
   GET /internal/usuarios?ids= de Identidad.
2. asignaturas (criterio 1): las filas de asignatura_ref que trae
   GET /asignaturas de Catalogo, la ruta publica.
3. perfiles (criterio 3, A-13): RN-01 otra vez, con la carrera y el nivel que
   trajo el paso 1 (el nivel no se copia, A-11). Desactiva los perfiles que ya
   no la cumplen y nunca reactiva uno.

Las llamadas a otros servicios van siempre fuera de una transaccion, y cada
escritura en su propia transaccion corta. Si un paso falla, su error queda en
el resultado como «<paso>: <TipoDeError>: <mensaje>», el mismo formato de
cerrar_y_expirar (HU-29), y se sigue con el paso siguiente: lo ya guardado
queda guardado. La reputacion de usuario_ref es un dato propio de Tutorias y
la sincronizacion nunca la escribe. La corre el comando sincronizar_copias.
"""

import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from .llamadas import (
    ServicioNoDisponible,
    asignaturas_del_catalogo,
    malla_cursada,
    usuarios_por_ids,
)
from .models import AsignaturaRef, PerfilTutor, UsuarioRef

logger = logging.getLogger(__name__)

# Ids por llamada a Identidad. Con 50 uuid, la primera linea de la peticion
# queda bajo los 4094 bytes que acepta gunicorn; Identidad acepta hasta 100.
TAMANO_LOTE = 50
# El tope de ck_usuario_nivel en Identidad. La malla de cada carrera se pide
# una vez entera y se filtra por el nivel de cada usuario.
NIVEL_MAXIMO = 12
# Las columnas de usuario_ref que son copia de Identidad. La reputacion no.
COLUMNAS_DE_COPIA = [
    "nombre",
    "apellido",
    "carrera_id",
    "sede_id",
    "activo",
    "actualizado_en",
]


@dataclass
class Resultado:
    """Lo que hizo una ejecucion: va a su fila de ejecucion_tarea."""

    refs_sincronizadas: int = 0
    perfiles_desactivados: int = 0
    errores: list[str] = field(default_factory=list)

    def anotar(self, paso, error):
        """Anota «<paso>: <TipoDeError>: <mensaje>», una vez cada texto."""
        texto = f"{paso}: {type(error).__name__}: {error}"
        if texto not in self.errores:
            self.errores.append(texto)


def sincronizar():
    """Los tres pasos, en orden. Devuelve el Resultado: los errores no se lanzan."""
    resultado = Resultado()
    # Lo que trajo Identidad de cada usuario en esta ejecucion: el paso 3 usa
    # su carrera y su nivel.
    traidos = {}
    _paso(resultado, "usuarios", _sincronizar_usuarios, traidos)
    _paso(resultado, "asignaturas", _sincronizar_asignaturas)
    _paso(resultado, "perfiles", _revisar_perfiles, traidos)
    return resultado


def _paso(resultado, paso, funcion, *argumentos):
    """Corre un paso. Si falla, anota el error y deja seguir al siguiente."""
    try:
        funcion(resultado, *argumentos)
    except ServicioNoDisponible as error:
        # llamadas.py ya dejo en el log lo que respondio el otro servicio.
        resultado.anotar(paso, error)
    except Exception as error:
        logger.exception("La sincronización falló en el paso %s", paso)
        resultado.anotar(paso, error)


# ------------------------------------------------------------ 1. usuarios


def _sincronizar_usuarios(resultado, traidos):
    """Las copias de usuario_ref, por lotes, de la mas antigua a la mas nueva."""
    ids = list(
        UsuarioRef.objects.order_by("actualizado_en", "usuario_id").values_list(
            "usuario_id", flat=True
        )
    )
    # Sin filas no se llama a Identidad. Si un lote falla, la excepcion corta
    # los siguientes: la proxima ejecucion empieza otra vez por las mas
    # antiguas, que son justo las que quedaron sin refrescar.
    for inicio in range(0, len(ids), TAMANO_LOTE):
        lote = ids[inicio : inicio + TAMANO_LOTE]
        datos = usuarios_por_ids(lote)
        resultado.refs_sincronizadas += _escribir_lote(lote, datos)
        for usuario_id in lote:
            if usuario_id in datos:
                traidos[usuario_id] = datos[usuario_id]


def _escribir_lote(lote, datos):
    """Escribe las copias de un lote, en una transaccion. Devuelve cuantas."""
    ahora = timezone.now()
    with transaction.atomic():
        # En orden de usuario_id: una ejecucion a mano y la del programador no
        # se bloquean entre si.
        filas = list(
            UsuarioRef.objects.select_for_update()
            .filter(usuario_id__in=lote)
            .order_by("usuario_id")
        )
        encontradas, faltantes = [], []
        for fila in filas:
            usuario = datos.get(fila.usuario_id)
            if usuario is None:
                faltantes.append(fila.usuario_id)
                continue
            fila.nombre = usuario["nombre"]
            fila.apellido = usuario["apellido"]
            fila.carrera_id = usuario["carrera_id"]
            fila.sede_id = usuario["sede_id"]
            fila.activo = usuario["activo"]
            fila.actualizado_en = ahora
            encontradas.append(fila)
        # Solo las columnas de copia: nunca save() de la fila entera.
        UsuarioRef.objects.bulk_update(encontradas, COLUMNAS_DE_COPIA)
        if faltantes:
            # Identidad no tiene la cuenta (RN-08). Como copias.py con
            # cuenta_inactiva: activo en false, y lo demas queda como estaba.
            UsuarioRef.objects.filter(usuario_id__in=faltantes).update(
                activo=False, actualizado_en=ahora
            )
    for usuario_id in faltantes:
        logger.warning(
            "Identidad no devolvió al usuario %s: su copia queda con activo "
            "en false (RN-08)",
            usuario_id,
        )
    return len(filas)


# ------------------------------------------------------------ 2. asignaturas


def _sincronizar_asignaturas(resultado):
    """Las copias de asignatura_ref, con la sigla y el nombre de Catalogo."""
    copias = set(AsignaturaRef.objects.values_list("asignatura_id", flat=True))
    if not copias:
        return
    catalogo = asignaturas_del_catalogo()
    ahora = timezone.now()
    with transaction.atomic():
        # Las que Catalogo no trae (desactivadas o borradas) no cambian:
        # asignatura_ref no tiene columna activo. Bloqueo en orden de
        # asignatura_id, por lo mismo que en los usuarios.
        filas = list(
            AsignaturaRef.objects.select_for_update()
            .filter(asignatura_id__in=copias & catalogo.keys())
            .order_by("asignatura_id")
        )
        # De la mas antigua a la mas nueva (criterio 1).
        filas.sort(key=lambda fila: (fila.actualizado_en, fila.asignatura_id))
        for fila in filas:
            fila.sigla = catalogo[fila.asignatura_id]["sigla"]
            fila.nombre = catalogo[fila.asignatura_id]["nombre"]
            fila.actualizado_en = ahora
        AsignaturaRef.objects.bulk_update(filas, ["sigla", "nombre", "actualizado_en"])
    resultado.refs_sincronizadas += len(filas)


# ------------------------------------------------------------ 3. perfiles


def _revisar_perfiles(resultado, traidos):
    """RN-01 otra vez para los perfiles activos de los usuarios del paso 1.

    La regla es la de perfiles.py: la asignatura tiene que estar en la malla
    vigente de la carrera del usuario, en un semestre menor que su nivel. No
    toca reservas, bloques ni usuario_ref. Una cuenta desactivada no es motivo
    para desactivar sus perfiles: la busqueda ya la deja fuera por
    usuario_ref.activo.
    """
    if not traidos:
        return
    perfiles = (
        PerfilTutor.objects.filter(activo=True, usuario_id__in=list(traidos))
        .select_related("asignatura")
        .order_by("usuario_id", "asignatura_id")
    )
    por_carrera = {}
    for perfil in perfiles:
        carrera_id = traidos[perfil.usuario_id]["carrera_id"]
        if carrera_id is None:
            # perfiles.py tampoco deja declarar sin carrera.
            _desactivar(resultado, perfil, "Identidad no trae su carrera")
        else:
            por_carrera.setdefault(carrera_id, []).append(perfil)

    # Una malla por carrera en cada ejecucion, aunque tenga varios tutores.
    for carrera_id, de_la_carrera in por_carrera.items():
        try:
            malla = malla_cursada(carrera_id, NIVEL_MAXIMO)
        except ServicioNoDisponible as error:
            # Ningun perfil de esta carrera cambia; las demas siguen.
            resultado.anotar("perfiles", error)
            continue
        for perfil in de_la_carrera:
            motivo = _no_cumple(perfil, traidos[perfil.usuario_id]["nivel"], malla)
            if motivo is not None:
                _desactivar(resultado, perfil, motivo)


def _no_cumple(perfil, nivel, malla):
    """Por que el perfil ya no cumple RN-01, o None si la cumple."""
    if not nivel:
        # perfiles.py tampoco deja declarar sin nivel.
        return "Identidad no trae su nivel"
    if malla is None:
        return "Catálogo no tiene su carrera activa"
    asignatura = malla.get(perfil.asignatura_id)
    if asignatura is None or asignatura["semestre"] > nivel - 1:
        return (
            "la asignatura no está en la malla de su carrera hasta el semestre "
            f"{nivel - 1}"
        )
    return None


def _desactivar(resultado, perfil, motivo):
    """Desactiva el perfil si sigue activo: un UPDATE, su propia transaccion."""
    # actualizado_en es auto_now, que update() no pone solo.
    cambiados = PerfilTutor.objects.filter(id=perfil.id, activo=True).update(
        activo=False, actualizado_en=timezone.now()
    )
    if not cambiados:
        return
    resultado.perfiles_desactivados += 1
    logger.warning(
        "Perfil %s desactivado (RN-01): usuario %s, asignatura %s (%s): %s",
        perfil.id,
        perfil.usuario_id,
        perfil.asignatura_id,
        perfil.asignatura.sigla,
        motivo,
    )
