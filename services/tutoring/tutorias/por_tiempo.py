"""Transiciones de la reserva que dispara el paso del tiempo (AD-10).

No son rutas de la API: las ejecuta el programador (HU-37), sin una peticion
de por medio.

- expirar_solicitudes (HU-28, criterio 5, RN-03): la solicitud que nadie
  respondio queda EXPIRADA cuando empieza su bloque.
- HU-29 le suma cerrar_realizadas y crea el comando cerrar_y_expirar, que las
  llama cada cinco minutos desde el programador y escribe la fila de
  ejecucion_tarea.
"""

from django.utils import timezone

from .models import BloqueDisponibilidad, EstadoReserva, Reserva


def expirar_solicitudes(ahora=None):
    """Pasa a EXPIRADA cada solicitud cuyo bloque ya empezo. Devuelve cuantas.

    Criterio 5 de HU-28 (RN-03, anexo A, seccion 9): cada reserva SOLICITADA
    cuyo bloque tiene inicio_en <= ahora queda EXPIRADA, con cerrada_en =
    ahora. Si ahora es None, usa timezone.now(). No cambia el bloque, no avisa
    a nadie (el anexo A no tiene plantilla para la expiracion) y no escribe
    ejecucion_tarea: esa fila la escribe el comando de HU-29.

    Es un solo UPDATE, con el estado en la tabla que se actualiza y el bloque
    en una subconsulta. No se escribe con bloque__inicio_en__lte: con ese
    filtro, Django arma un UPDATE ... WHERE id IN (SELECT ...) que deja el
    estado adentro de la subconsulta. Si una confirmacion de HU-22 termina
    justo entre medio, PostgreSQL no vuelve a revisar el estado y pisaria una
    reserva recien CONFIRMADA. Con el estado en el UPDATE, PostgreSQL lo
    revisa otra vez en la fila que tuvo que esperar, y la salta.

    Por lo mismo, dos ejecuciones seguidas, o al mismo tiempo, no expiran dos
    veces la misma solicitud: la segunda ya no la encuentra SOLICITADA.
    """
    if ahora is None:
        ahora = timezone.now()
    empezados = BloqueDisponibilidad.objects.filter(inicio_en__lte=ahora)
    return Reserva.objects.filter(
        estado=EstadoReserva.SOLICITADA,
        bloque_id__in=empezados.values("id"),
    ).update(estado=EstadoReserva.EXPIRADA, cerrada_en=ahora)
