"""Figura 5 del Pilar 4 (versión 2.0): carta Gantt de las 44 historias y SCRUM-70.

Lee 08_carta_gantt.csv (junto a este archivo) y escribe 08_carta_gantt.png.

Qué muestra cada fila:
- Barra clara: el sprint de la historia en la replanificación del 25-09
  (columna «Sprint» de la tabla 3.2 del Pilar 4). HU-38 a HU-41, que nacieron el 29-10,
  muestran su sprint de Jira. HU-42 a HU-44 y SCRUM-70 no tienen sprint.
- Marca oscura: el día y la hora en que se fusionó a develop el Pull Request de la
  historia (historial de develop al 02-11). Rellena si la historia está Finalizada en
  Jira; vacía si el Pull Request fue parcial y la historia sigue abierta.
- Color: el responsable de la historia en Jira al 02-11.

Paleta comprobada con un validador de contraste y daltonismo (tres colores, todos los
pares, fondo blanco): azul #2a78d6, naranjo #eb6834 y aguamarina #1baf7a; las barras
usan un tinte al 40 % y las marcas un tono al 15 % más oscuro. La columna «Responsable»
repite el nombre, para que el color nunca sea la única señal.

El tamaño de la figura es el del documento (8,33 × 5,95 pulgadas en la página
horizontal del anexo), así que ningún texto baja de 7 pt.
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.transforms import blended_transform_factory

AQUI = Path(__file__).resolve().parent

_DISPONIBLES = {f.name for f in font_manager.fontManager.ttflist}
plt.rcParams["font.family"] = [
    f for f in ("Carlito", "Calibri", "DejaVu Sans") if f in _DISPONIBLES
]

AZUL_TITULO = "#1F4E79"
TINTA = "#262626"
TINTA_2 = "#595959"
GRILLA = "#D0D0D0"

BASE = {"Bryan": "#2a78d6", "Francisco": "#eb6834", "Damaris": "#1baf7a", "": "#9E9E9E"}


def _mezcla(hexa, otro, k):
    a = [int(hexa[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(otro[i : i + 2], 16) for i in (1, 3, 5)]
    rojo, verde, azul = (round(x * (1 - k) + y * k) for x, y in zip(a, b, strict=True))
    return f"#{rojo:02X}{verde:02X}{azul:02X}"


CLARO = {k: _mezcla(v, "#FFFFFF", 0.40) for k, v in BASE.items()}
OSCURO = {k: _mezcla(v, "#000000", 0.15) for k, v in BASE.items()}

SPRINTS = {
    "Cimientos": (datetime(2026, 9, 14), datetime(2026, 9, 21)),
    "Sprint 1": (datetime(2026, 9, 21), datetime(2026, 10, 5)),
    "Sprint 2": (datetime(2026, 10, 5), datetime(2026, 10, 19)),
    "Sprint 3": (datetime(2026, 10, 19), datetime(2026, 11, 2)),
    "Sprint 4": (datetime(2026, 11, 2), datetime(2026, 11, 9)),
    "Semanas 14 y 15": (datetime(2026, 11, 9), datetime(2026, 11, 22)),
}
BANDAS = [
    ("Cimientos", "Cimientos"),
    ("Sprint 1", "Sprint 1"),
    ("Sprint 2", "Sprint 2"),
    ("Sprint 3", "Sprint 3"),
    ("Sprint 4", "Sprint 4"),
    ("Semanas 14 y 15", "Semanas 14 y 15"),
]
INICIO, FIN = datetime(2026, 9, 14), datetime(2026, 11, 22)
REPLANIFICACION = datetime(2026, 9, 25, 12)
CONGELAMIENTO = datetime(2026, 11, 9)


def leer():
    with open(AQUI / "08_carta_gantt.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    filas = leer()
    n = len(filas)

    fig = plt.figure(figsize=(8.33, 5.95), dpi=300)
    ax_izq, ax_der, ax_abajo, ax_arriba = 0.435, 0.988, 0.108, 0.94
    ax = fig.add_axes([ax_izq, ax_abajo, ax_der - ax_izq, ax_arriba - ax_abajo])
    ax.set_xlim(mdates.date2num(INICIO), mdates.date2num(FIN))
    ax.set_ylim(n - 0.5, -0.5)
    ax.axis("off")
    filas_t = blended_transform_factory(fig.transFigure, ax.transData)

    # Bandas alternas por sprint y grilla de lunes
    for k, (clave, rotulo) in enumerate(BANDAS):
        a, b = SPRINTS[clave]
        xa, xb = mdates.date2num(a), mdates.date2num(b)
        if k % 2 == 0:
            ax.add_patch(
                Rectangle(
                    (xa, -0.5),
                    xb - xa,
                    n,
                    facecolor="#F4F6F9",
                    edgecolor="none",
                    zorder=0,
                )
            )
        ax.axvline(xa, color="#A6A6A6", lw=0.6, zorder=1)
        # rótulo de la banda, sobre el eje
        fig.text(0, 0, "")
        ax.text(
            (xa + xb) / 2,
            -1.85,
            rotulo,
            ha="center",
            va="center",
            fontsize=7.5,
            color=AZUL_TITULO,
            fontweight="bold",
            clip_on=False,
        )
    ax.axvline(mdates.date2num(FIN), color="#A6A6A6", lw=0.6, zorder=1)
    lunes = INICIO
    while lunes < FIN:
        ax.text(
            mdates.date2num(lunes) + 0.3,
            -0.85,
            lunes.strftime("%d-%m"),
            ha="left",
            va="center",
            fontsize=7,
            color=TINTA_2,
            clip_on=False,
        )
        lunes += timedelta(days=7)

    # Separadores entre grupos y rótulo del grupo a la izquierda
    grupo_anterior = None
    for i, f in enumerate(filas):
        if f["grupo"] != grupo_anterior and grupo_anterior is not None:
            ax.plot(
                [0.006, ax_der],
                [i - 0.5, i - 0.5],
                transform=filas_t,
                color=GRILLA,
                lw=0.6,
                clip_on=False,
                zorder=1,
            )
        grupo_anterior = f["grupo"]

    # Encabezados de las columnas de texto
    fig.text(
        0.008,
        ax_arriba + 0.012,
        "Historia (resumen de Jira)",
        ha="left",
        va="bottom",
        fontsize=7.5,
        color=AZUL_TITULO,
        fontweight="bold",
    )
    fig.text(
        0.352,
        ax_arriba + 0.012,
        "Responsable",
        ha="left",
        va="bottom",
        fontsize=7.5,
        color=AZUL_TITULO,
        fontweight="bold",
    )

    for i, f in enumerate(filas):
        resp = f["responsable_jira"]
        # Columna de texto
        ax.text(
            0.008,
            i,
            f["id"],
            transform=filas_t,
            ha="left",
            va="center",
            fontsize=7,
            color=TINTA,
            fontweight="bold",
            clip_on=False,
        )
        ax.text(
            0.068,
            i,
            f["resumen_jira"],
            transform=filas_t,
            ha="left",
            va="center",
            fontsize=7,
            color=TINTA,
            clip_on=False,
        )
        if resp:
            ax.plot(
                [0.357],
                [i],
                transform=filas_t,
                marker="s",
                ms=4.2,
                color=BASE[resp],
                clip_on=False,
                zorder=3,
            )
        ax.text(
            0.367,
            i,
            resp if resp else "—",
            transform=filas_t,
            ha="left",
            va="center",
            fontsize=7,
            color=TINTA if resp else TINTA_2,
            clip_on=False,
        )

        # Barra clara: sprint de la replanificación (o de Jira para HU-38 a HU-41)
        if f["sprint_barra"]:
            a, b = SPRINTS[f["sprint_barra"]]
            xa, xb = mdates.date2num(a), mdates.date2num(b)
            ax.add_patch(
                Rectangle(
                    (xa + 0.15, i - 0.31),
                    xb - xa - 0.3,
                    0.62,
                    facecolor=CLARO[resp],
                    edgecolor="none",
                    zorder=2,
                )
            )
        else:
            ax.text(
                mdates.date2num(INICIO) + 1.0,
                i,
                f["sprint_jira"].replace("sin sprint", "sin sprint en Jira"),
                ha="left",
                va="center",
                fontsize=7,
                color=TINTA_2,
                style="italic",
                zorder=6,
                bbox=dict(
                    boxstyle="square,pad=0.1", facecolor="white", edgecolor="none"
                ),
            )

        # Marca oscura: fusión a develop
        if f["fusion"]:
            t = datetime.strptime(f["fusion"], "%Y-%m-%d %H:%M")
            xt = mdates.date2num(t)
            if f["tipo_fusion"] == "completa":
                ax.plot(
                    xt,
                    i,
                    marker="D",
                    ms=5.0,
                    color=OSCURO[resp],
                    mec="white",
                    mew=0.7,
                    zorder=5,
                )
            else:
                ax.plot(
                    xt,
                    i,
                    marker="D",
                    ms=4.6,
                    color="white",
                    mec=OSCURO[resp],
                    mew=1.2,
                    zorder=5,
                )

    # Líneas de la replanificación y del congelamiento
    xr = mdates.date2num(REPLANIFICACION)
    ax.plot([xr, xr], [-0.5, n - 0.5], color=TINTA_2, lw=0.9, ls=(0, (3, 2)), zorder=4)
    ax.text(
        xr,
        n - 0.1,
        "25-09: replanificación",
        ha="center",
        va="top",
        fontsize=7,
        color=TINTA_2,
        clip_on=False,
    )
    xc = mdates.date2num(CONGELAMIENTO)
    ax.plot([xc, xc], [-0.5, n - 0.5], color="#000000", lw=1.2, zorder=4)
    ax.text(
        xc,
        n - 0.1,
        "08-11: congelamiento",
        ha="center",
        va="top",
        fontsize=7,
        color="#000000",
        fontweight="bold",
        clip_on=False,
    )

    # Leyenda, en dos filas abajo (el título y la fuente van en el pie de la figura
    # del documento)
    elementos = [
        (
            Rectangle((0, 0), 1, 1, facecolor="#C9CED6", edgecolor="none"),
            "sprint de la replanificación (HU-38 a HU-41: sprint de Jira)",
        ),
        (
            Line2D(
                [],
                [],
                marker="D",
                ls="none",
                ms=5,
                color="#3A3A3A",
                mec="white",
                mew=0.7,
            ),
            "fusionada a develop: historia Finalizada",
        ),
        (
            Line2D(
                [],
                [],
                marker="D",
                ls="none",
                ms=4.6,
                color="white",
                mec="#3A3A3A",
                mew=1.2,
            ),
            "Pull Request parcial: la historia sigue abierta",
        ),
    ]
    fig.legend(
        [e for e, _ in elementos],
        [t for _, t in elementos],
        loc="lower left",
        bbox_to_anchor=(0.003, 0.028),
        ncol=3,
        frameon=False,
        fontsize=7.5,
        handlelength=1.6,
        handletextpad=0.5,
        columnspacing=1.6,
    )
    personas = [
        (Line2D([], [], marker="s", ls="none", ms=5, color=BASE[p]), p)
        for p in ("Bryan", "Francisco", "Damaris")
    ]
    fig.text(
        0.0115,
        0.018,
        "Responsable en Jira al 02-11:",
        ha="left",
        va="center",
        fontsize=7.5,
        color=TINTA,
    )
    fig.legend(
        [e for e, _ in personas],
        [t for _, t in personas],
        loc="center left",
        bbox_to_anchor=(0.19, 0.018),
        ncol=3,
        frameon=False,
        fontsize=7.5,
        handlelength=1.0,
        handletextpad=0.4,
        columnspacing=1.2,
    )

    salida = AQUI / "08_carta_gantt.png"
    fig.savefig(salida, dpi=300, facecolor="white")
    print(salida)


if __name__ == "__main__":
    main()
