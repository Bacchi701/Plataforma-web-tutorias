"""API publica de Catalogo (HU-12, Pilar 2 seccion 4.2).

Solo lectura y sin token: carreras, sedes y asignaturas son datos de
referencia. Los endpoints /internal llegan con el resto de HU-12.
"""

from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from .models import Asignatura, Carrera, MallaAsignatura, Sede

# Tope de resultados de la busqueda: suficiente para una pantalla.
MAXIMO_RESULTADOS = 50


def carrera_json(carrera):
    return {
        "id": str(carrera.id),
        "codigo": carrera.codigo,
        "nombre": carrera.nombre,
        "escuela": carrera.escuela,
    }


def asignatura_json(asignatura):
    return {
        "id": str(asignatura.id),
        "sigla": asignatura.sigla,
        "nombre": asignatura.nombre,
        "creditos": asignatura.creditos,
    }


def carrera_activa(carrera_id):
    carrera = Carrera.objects.filter(id=carrera_id, activa=True).first()
    if carrera is None:
        raise NotFound("No existe una carrera activa con ese identificador.")
    return carrera


def malla_vigente(carrera):
    return carrera.mallas.filter(vigente_hasta__isnull=True).first()


def malla_json(malla):
    if malla is None:
        return None
    return {"version": malla.version, "vigente_desde": malla.vigente_desde}


@api_view(["GET"])
def listar_carreras(request):
    carreras = Carrera.objects.filter(activa=True).order_by("nombre")
    return Response([carrera_json(c) for c in carreras])


@api_view(["GET"])
def detalle_carrera(request, carrera_id):
    carrera = carrera_activa(carrera_id)
    cuerpo = carrera_json(carrera)
    cuerpo["malla_vigente"] = malla_json(malla_vigente(carrera))
    return Response(cuerpo)


@api_view(["GET"])
def asignaturas_de_carrera(request, carrera_id):
    """Malla vigente de la carrera, agrupada por semestre (HU-12, criterio 3)."""
    carrera = carrera_activa(carrera_id)
    malla = malla_vigente(carrera)

    semestres = {}
    if malla is not None:
        filas = (
            MallaAsignatura.objects.filter(malla=malla, asignatura__activa=True)
            .select_related("asignatura")
            .order_by("semestre", "asignatura__sigla")
        )
        for fila in filas:
            semestres.setdefault(fila.semestre, []).append(
                asignatura_json(fila.asignatura)
            )

    return Response(
        {
            "carrera": carrera_json(carrera),
            "malla": malla_json(malla),
            "semestres": [
                {"semestre": numero, "asignaturas": asignaturas}
                for numero, asignaturas in semestres.items()
            ],
        }
    )


@api_view(["GET"])
def buscar_asignaturas(request):
    """GET /asignaturas?buscar= por sigla o nombre, aunque sea parcial."""
    texto = request.query_params.get("buscar", "").strip()
    asignaturas = Asignatura.objects.filter(activa=True)
    if texto:
        asignaturas = asignaturas.filter(
            Q(sigla__icontains=texto) | Q(nombre__icontains=texto)
        )
    asignaturas = asignaturas.order_by("sigla")[:MAXIMO_RESULTADOS]
    return Response([asignatura_json(a) for a in asignaturas])


@api_view(["GET"])
def listar_sedes(request):
    sedes = Sede.objects.filter(activa=True).order_by("nombre")
    return Response(
        [
            {
                "id": str(s.id),
                "codigo": s.codigo,
                "nombre": s.nombre,
                "region": s.region,
            }
            for s in sedes
        ]
    )
