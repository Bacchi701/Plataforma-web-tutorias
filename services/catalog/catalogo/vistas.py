"""API publica de Catalogo (HU-12, Pilar 2 seccion 4.2).

Solo lectura y sin token: carreras, sedes y asignaturas son datos de
referencia. Los endpoints /internal llegan con el resto de HU-12.
"""

from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from .models import Asignatura, Carrera, MallaAsignatura, Sede

# Tope de resultados de la busqueda: multiplo de 3 para cuadricula de tarjetas.
MAXIMO_RESULTADOS = 48


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
        "area": getattr(asignatura, "area", None) or "",
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
    """GET /asignaturas?buscar=&pagina=&limite= con búsqueda global y paginación."""
    texto = request.query_params.get("buscar", "").strip()
    area = request.query_params.get("area", "").strip()

    try:
        pagina = max(1, int(request.query_params.get("pagina") or request.query_params.get("page") or 1))
    except (ValueError, TypeError):
        pagina = 1

    try:
        limite = max(1, min(200, int(request.query_params.get("limite") or request.query_params.get("limit") or MAXIMO_RESULTADOS)))
    except (ValueError, TypeError):
        limite = MAXIMO_RESULTADOS

    asignaturas = Asignatura.objects.filter(activa=True)
    if area:
        asignaturas = asignaturas.filter(area=area)
    if texto:
        asignaturas = asignaturas.filter(
            Q(sigla__icontains=texto) | Q(nombre__icontains=texto)
        )

    total = asignaturas.count()
    total_paginas = max(1, (total + limite - 1) // limite)
    inicio = (pagina - 1) * limite
    fin = inicio + limite

    elementos = asignaturas.order_by("sigla")[inicio:fin]
    datos = [asignatura_json(a) for a in elementos]

    headers = {
        "X-Total-Count": str(total),
        "X-Total-Pages": str(total_paginas),
        "X-Current-Page": str(pagina),
        "X-Per-Page": str(limite),
    }

    if request.query_params.get("paginado") == "1" or request.query_params.get("formato") == "paginado":
        return Response(
            {
                "total": total,
                "pagina": pagina,
                "total_paginas": total_paginas,
                "limite": limite,
                "resultados": datos,
            },
            headers=headers,
        )

    return Response(datos, headers=headers)


@api_view(["GET"])
def listar_areas(request):
    """GET /areas lista única de áreas de conocimiento de las asignaturas."""
    areas = (
        Asignatura.objects.filter(activa=True)
        .exclude(area__isnull=True)
        .exclude(area="")
        .values_list("area", flat=True)
        .distinct()
        .order_by("area")
    )
    return Response(list(areas))



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
