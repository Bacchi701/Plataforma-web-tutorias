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


def cerrar_realizadas(ahora=None):
    """Pasa a REALIZADA cada tutoria CONFIRMADA que ya termino. Devuelve cuantas.

    Criterio 1 de HU-29 (CA6, anexo A, seccion 9): cada reserva CONFIRMADA
    cuyo bloque tiene fin_en <= ahora queda REALIZADA, y desde ahi el
    estudiante la puede evaluar (HU-25). Si ahora es None, usa timezone.now().

    Solo escribe estado. cerrada_en no, porque REALIZADA no es un estado
    terminal: cerrada_en la escribe EVALUADA (HU-25). El bloque sigue OCUPADO,
    porque ux_reserva_bloque_ocupado cubre tambien REALIZADA. No mira
    estado_pago: un pago pendiente o fallido no bloquea la sesion (RN-05). No
    avisa a nadie y no escribe ejecucion_tarea: esa fila la escribe el comando
    cerrar_y_expirar.

    Es un solo UPDATE, con el estado en la tabla que se actualiza y el bloque
    en una subconsulta, por lo que explica expirar_solicitudes. Asi, dos
    ejecuciones seguidas, o al mismo tiempo (el programador y una a mano), no
    cierran dos veces la misma reserva: la segunda, que espera a la primera en
    esa fila, vuelve a revisar el estado y ya no la encuentra CONFIRMADA.
    """
    if ahora is None:
        ahora = timezone.now()
    terminados = BloqueDisponibilidad.objects.filter(fin_en__lte=ahora)
    return Reserva.objects.filter(
        estado=EstadoReserva.CONFIRMADA,
        bloque_id__in=terminados.values("id"),
    ).update(estado=EstadoReserva.REALIZADA)
