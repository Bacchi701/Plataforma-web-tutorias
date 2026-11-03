"""Figura 2 del documento 10 (User Story Mapping, versión 1.1): story map al 02-11-2026.

Dibuja el recorrido del usuario (columnas: la base del sistema y las nueve actividades)
y, de arriba abajo, una franja por sprint, con el mismo estilo de la figura 1 del
documento (el plan del 27-09).

Datos: 11_story_map.csv, junto a este archivo. Cada fila es una tarjeta, en el orden en
que se apila:
- franja: Sprint 1, Sprint 2, Sprint 3, Sprint 4, Semanas 14 y 15 o Fuera del MVP;
- actividad: una de las de ACTIVIDADES (vacía si todavía no tiene una asignada: la
  tarjeta no se dibuja y la nota de la leyenda lo dice);
- id y titulo: lo que muestra la tarjeta;
- tipo: finalizada, usuario, tecnica o candidato.
Fuentes de los datos (al 02-11-2026): Jira (estado y sprint de cada historia; HU-01 y
HU-02, anteriores al tablero, en el sprint en que se fusionaron en develop) y la
figura 1 del documento 10 (actividad de cada historia). HU-40 va en «4. Buscar un
tutor» y HU-41 en «2. Completar el perfil», por lo que hace cada una; HU-38 y HU-39
todavía no tienen una actividad.

Uso: python 11_story_map.py  (escribe 11_story_map.png junto a este archivo). Necesita
Pillow 10.1 o más nuevo. Usa la letra Carlito (o Calibri, que tiene las mismas medidas);
si no encuentra ninguna, usa DejaVu Sans y la figura cambia un poco.
"""

import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

AQUI = Path(__file__).resolve().parent
DATOS = AQUI / "11_story_map.csv"
SALIDA = AQUI / "11_story_map.png"

LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
SS = 4  # sobremuestreo de las cajas redondeadas

# Medidas de la figura 1 del documento 10 (en píxeles de la imagen, de 3324 de ancho)
ANCHO = 3324
COL_X0, COL_PASO, COL_ANCHO = 312, 296, 284  # columnas de las actividades
ANCHO_TEXTO = 251.5  # corte de línea del título de una tarjeta
ETQ_X0, ETQ_X1 = 64, 299  # columna de las etiquetas de las franjas
AZUL, GRIS_ENCABEZADO = (31, 78, 121), (89, 89, 89)
SEPARADOR = (159, 179, 200)
ROJO = (192, 80, 77)
TINTA, TINTA_GRIS, TINTA_NOTA = (27, 27, 27), (89, 89, 89), (85, 85, 85)
# Por tipo: relleno, borde y patrón del borde (None = continuo; (trazo, espacio) =
# discontinuo)
ESTILOS = {
    "finalizada": ((226, 239, 218), (84, 130, 53), None),
    "usuario": ((255, 242, 204), (191, 143, 0), None),
    "tecnica": ((242, 242, 242), (127, 127, 127), (6, 4)),
    "candidato": ((255, 255, 255), (127, 127, 127), (2, 2)),
}

# Columnas: nombre (como en el .csv) y líneas del encabezado
ACTIVIDADES = [
    ("Base del sistema", ["Base del sistema"]),
    ("1. Crear cuenta y entrar", ["1. Crear cuenta y", "entrar"]),
    ("2. Completar el perfil", ["2. Completar el", "perfil"]),
    ("3. Ofrecer tutorías", ["3. Ofrecer tutorías"]),
    ("4. Buscar un tutor", ["4. Buscar un tutor"]),
    ("5. Solicitar y coordinar", ["5. Solicitar y", "coordinar"]),
    ("6. Pagar", ["6. Pagar"]),
    ("7. Cancelar o cerrar", ["7. Cancelar o cerrar"]),
    ("8. Evaluar", ["8. Evaluar"]),
    ("9. Administrar", ["9. Administrar"]),
]
# Franjas: nombre, líneas bajo el nombre y si van bajo la línea roja
FRANJAS = [
    ("Sprint 1", ["21-09 al 04-10"], False),
    ("Sprint 2", ["05 al 18-10"], False),
    ("Sprint 3", ["19-10 al 01-11"], False),
    ("Sprint 4", ["02 al 08-11", "en curso"], False),
    ("Semanas 14 y 15", ["después del 08-11"], False),
    ("Fuera del MVP", ["Should y Could"], True),
]
LEYENDA = [
    ("Finalizada", "finalizada"),
    ("Historia de usuario", "usuario"),
    ("Técnica o de calidad", "tecnica"),
    ("Candidato fuera del MVP", "candidato"),
]
NOTA = (
    "Estados de Jira al 02-11. HU-03, HU-04 y HU-05 se fusionaron el 21-10, pero Jira"
    " las cuenta en el Sprint 2."
)


def fuente(tamano, negrita=False):
    nombres = (
        ["Carlito-Bold.ttf", "calibrib.ttf", "Calibri Bold.ttf", "DejaVuSans-Bold.ttf"]
        if negrita
        else ["Carlito-Regular.ttf", "calibri.ttf", "Calibri.ttf", "DejaVuSans.ttf"]
    )
    for nombre in nombres:
        for ruta in (AQUI / nombre, nombre):
            try:
                return ImageFont.truetype(str(ruta), tamano)
            except OSError:
                pass
    return ImageFont.load_default(size=tamano)


F_ID, F_TITULO = fuente(27.5, True), fuente(27.5)
F_ENCABEZADO, F_FRANJA, F_SUB, F_LEYENDA = (
    fuente(30.2, True),
    fuente(29.3, True),
    fuente(26.3),
    fuente(27.5),
)


def envolver(texto, letra, ancho):
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = (actual + " " + palabra).strip()
        if letra.getlength(prueba) <= ancho or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def caja(img, box, relleno, borde, patron, radio=8, ancho_borde=2):
    """Caja redondeada con antialias; borde continuo o discontinuo (patrón en px)."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0 + 1, y1 - y0 + 1
    capa = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    if patron is None:
        d.rounded_rectangle(
            [0, 0, w * SS - 1, h * SS - 1],
            radius=radio * SS,
            fill=relleno + (255,),
            outline=borde + (255,),
            width=ancho_borde * SS,
        )
    else:
        d.rounded_rectangle(
            [0, 0, w * SS - 1, h * SS - 1], radius=radio * SS, fill=relleno + (255,)
        )
        trazo, espacio = patron[0] * SS, patron[1] * SS
        bw, r = ancho_borde * SS, radio * SS
        for ax, ay, bx in ((r, 0, w * SS - r), (r, h * SS - bw, w * SS - r)):
            x = ax
            while x < bx:
                d.rectangle(
                    [x, ay, min(x + trazo, bx) - 1, ay + bw - 1], fill=borde + (255,)
                )
                x += trazo + espacio
        for ax, ay, by in ((0, r, h * SS - r), (w * SS - bw, r, h * SS - r)):
            y = ay
            while y < by:
                d.rectangle(
                    [ax, y, ax + bw - 1, min(y + trazo, by) - 1], fill=borde + (255,)
                )
                y += trazo + espacio
        for cx, cy, a0 in (
            (r, r, 180),
            (w * SS - 1 - r, r, 270),
            (w * SS - 1 - r, h * SS - 1 - r, 0),
            (r, h * SS - 1 - r, 90),
        ):
            d.arc(
                [cx - r, cy - r, cx + r, cy + r],
                a0,
                a0 + 90,
                fill=borde + (255,),
                width=bw,
            )
    capa = capa.resize((w, h), LANCZOS)
    img.paste(capa, (x0, y0), capa)


def alto_tarjeta(titulo):
    return 86 + 32 * (len(envolver(titulo, F_TITULO, ANCHO_TEXTO)) - 1)


def tarjeta(img, d, x0, y0, ident, titulo, tipo):
    relleno, borde, patron = ESTILOS[tipo]
    lineas = envolver(titulo, F_TITULO, ANCHO_TEXTO)
    h = 86 + 32 * (len(lineas) - 1)
    caja(img, (x0, y0, x0 + COL_ANCHO - 1, y0 + h - 1), relleno, borde, patron)
    color = TINTA_GRIS if tipo == "candidato" else TINTA
    d.text((x0 + 15, y0 + 34), ident, font=F_ID, fill=color, anchor="ls")
    for i, s in enumerate(lineas):
        d.text((x0 + 15, y0 + 69 + 32 * i), s, font=F_TITULO, fill=color, anchor="ls")
    return h


def separador(d, y, rojo=False):
    fin = COL_X0 + COL_PASO * 9 + COL_ANCHO
    if rojo:
        x = ETQ_X0
        while x < fin:
            d.rectangle([x, y, min(x + 11, fin - 1), y + 3], fill=ROJO)
            x += 21
        return
    d.rectangle([ETQ_X0, y, ETQ_X1, y + 3], fill=SEPARADOR)
    for k in range(10):
        x0 = COL_X0 + COL_PASO * k
        d.rectangle([x0, y, x0 + COL_ANCHO - 1, y + 3], fill=SEPARADOR)


def leer_datos():
    columnas = {nombre: k for k, (nombre, _) in enumerate(ACTIVIDADES)}
    celdas = {franja: {} for franja, _, _ in FRANJAS}
    sin_actividad = []
    with open(DATOS, encoding="utf-8", newline="") as f:
        for fila in csv.DictReader(f):
            if fila["tipo"] not in ESTILOS:
                raise ValueError(f"{fila['id']}: tipo desconocido {fila['tipo']!r}")
            if not fila["actividad"].strip():
                sin_actividad.append(fila["id"])
                continue
            k = columnas[fila["actividad"]]
            celdas[fila["franja"]].setdefault(k, []).append(
                (fila["id"], fila["titulo"], fila["tipo"])
            )
    return celdas, sin_actividad


def nota_sin_actividad(ids):
    if not ids:
        return ""
    lista = ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " y " + ids[-1]
    verbo = (
        "no tiene actividad asignada y no se muestra"
        if len(ids) == 1
        else "no tienen actividad asignada y no se muestran"
    )
    return f" {lista} {verbo}."


def dibujar():
    celdas, sin_actividad = leer_datos()
    alturas = []
    for franja, _, _ in FRANJAS:
        pila = 0
        for tarjetas in celdas[franja].values():
            pila = max(
                pila,
                sum(alto_tarjeta(t) for _, t, _ in tarjetas) + 10 * (len(tarjetas) - 1),
            )
        alturas.append(max(pila, 86))
    alto = 172 + sum(16 + a + 22 for a in alturas) + 14 + 52 + 56
    img = Image.new("RGB", (ANCHO, alto), (255, 255, 255))
    d = ImageDraw.Draw(img)
    # encabezados de las actividades
    for k, (_, lineas) in enumerate(ACTIVIDADES):
        x0 = COL_X0 + COL_PASO * k
        color = GRIS_ENCABEZADO if k == 0 else AZUL
        caja(img, (x0, 56, x0 + COL_ANCHO - 1, 160), color, color, None, radio=10)
        bases = [116] if len(lineas) == 1 else [98, 133]
        for s, b in zip(lineas, bases, strict=True):
            d.text(
                (x0 + COL_ANCHO / 2, b),
                s,
                font=F_ENCABEZADO,
                fill=(255, 255, 255),
                anchor="ms",
            )
    # franjas
    y = 172
    for (franja, subs, bajo_linea_roja), alto_franja in zip(
        FRANJAS, alturas, strict=True
    ):
        separador(d, y, rojo=bajo_linea_roja)
        tope = y + 16
        for k, tarjetas in celdas[franja].items():
            yy = tope
            for ident, titulo, tipo in tarjetas:
                yy += (
                    tarjeta(img, d, COL_X0 + COL_PASO * k, yy, ident, titulo, tipo) + 10
                )
        centro = (y + 4 + tope + alto_franja + 22 - 1) / 2 + 3
        y0 = centro - 17 * len(subs)
        d.text(
            (72, y0),
            franja,
            font=F_FRANJA,
            fill=ROJO if bajo_linea_roja else AZUL,
            anchor="ls",
        )
        for i, s in enumerate(subs):
            d.text((72, y0 + 34 * (i + 1)), s, font=F_SUB, fill=TINTA_GRIS, anchor="ls")
        y = tope + alto_franja + 22
    # leyenda y nota
    yl = y + 14
    x = 64
    for texto, tipo in LEYENDA:
        relleno, borde, patron = ESTILOS[tipo]
        x1 = int(round(x + F_LEYENDA.getlength(texto) + 30))
        caja(img, (x, yl, x1, yl + 51), relleno, borde, patron, radio=6)
        d.text(
            (x + 14, yl + 34),
            texto,
            font=F_LEYENDA,
            fill=TINTA_GRIS if tipo == "candidato" else TINTA,
            anchor="ls",
        )
        x = x1 + 39
    d.text(
        (x, yl + 34),
        NOTA + nota_sin_actividad(sin_actividad),
        font=F_LEYENDA,
        fill=TINTA_NOTA,
        anchor="ls",
    )
    return img


if __name__ == "__main__":
    figura = dibujar()
    figura.save(SALIDA)
    print(f"{SALIDA.name}: {figura.width} × {figura.height} px")
