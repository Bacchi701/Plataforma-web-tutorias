"""Figura 4 del Pilar 4 (versión 2.0): cronograma de la replanificación del 25-09-2026.

Fuentes de los datos (al 02-11-2026):
- Calendario: replanificación del 25-09 (Pilar 4, sección 1), cuatro sprints y
  congelamiento del desarrollo el 08-11; semanas 14 y 15 (cierre) y Fase 3
  (semanas 16 a 18).
- Fechas de Jira: Sprint 2 cerrado el 23-10; Sprint 3 planificado el 23-10 y
  cerrado el 02-11.
- Hitos: 16-10 (avance de la Fase 2) y 30-10 (sesión obligatoria con el profesor).
- Feriados: Pilar 4, sección 1.2.

Uso: python 07_cronograma.py  (escribe 07_cronograma.png junto a este archivo).
El tamaño de la figura es el de la página (6,5 pulgadas de ancho), así que los puntos
de letra son los del documento: ninguno baja de 7 pt.
"""

from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Rectangle

AQUI = Path(__file__).resolve().parent

_DISPONIBLES = {f.name for f in font_manager.fontManager.ttflist}
plt.rcParams["font.family"] = [
    f for f in ("Carlito", "Calibri", "DejaVu Sans") if f in _DISPONIBLES
]

AZUL_TITULO = "#1F4E79"
TINTA = "#262626"
TINTA_2 = "#595959"
GRILLA = "#D9D9D9"
FERIADO = "#B03A2E"

# Fases: nombre, inicio, fin (inclusive), color, descripción y si la descripción
# se alinea a la derecha
FASES = [
    (
        "Planificación",
        date(2026, 9, 7),
        date(2026, 9, 13),
        "#9DB5D6",
        "cinco pilares, repositorio y maquetas",
        False,
    ),
    (
        "Cimientos",
        date(2026, 9, 14),
        date(2026, 9, 20),
        "#6C93C4",
        "el sistema se levanta con un comando (HU-01, fusionada el 21-09)",
        False,
    ),
    (
        "Sprint 1",
        date(2026, 9, 21),
        date(2026, 10, 4),
        "#2E75B6",
        "Registro, verificación e inicio de sesión (CA1); sin tablero en Jira",
        False,
    ),
    (
        "Sprint 2",
        date(2026, 10, 5),
        date(2026, 10, 18),
        "#2E75B6",
        "Cerrar lo abierto del Sprint 1 y, si alcanzaba, perfil y asignaturas",
        False,
    ),
    (
        "Sprint 3",
        date(2026, 10, 19),
        date(2026, 11, 1),
        "#2E75B6",
        "Flujo de reservas para la sesión del 30-10 (planificado el 23-10)",
        False,
    ),
    (
        "Sprint 4",
        date(2026, 11, 2),
        date(2026, 11, 8),
        "#2E75B6",
        "MVP completo antes del congelamiento",
        False,
    ),
    (
        "Cierre",
        date(2026, 11, 9),
        date(2026, 11, 21),
        "#1F4E79",
        "Semanas 14 y 15: ensayo, informe final y presentación",
        True,
    ),
    (
        "Fase 3",
        date(2026, 11, 23),
        date(2026, 12, 12),
        "#7F7F7F",
        "Semanas 16 a 18: presentación a la comisión",
        True,
    ),
]

INICIO = date(2026, 9, 7)
FIN = date(2026, 12, 14)
CIERRES = [date(2026, 10, 4), date(2026, 10, 18), date(2026, 11, 1), date(2026, 11, 8)]
HITOS = [
    (date(2026, 9, 25), "25-09\nreplanificación"),
    (date(2026, 10, 16), "16-10\navance Fase 2"),
    (date(2026, 10, 30), "30-10\nsesión obligatoria"),
]
FERIADOS = [
    (date(2026, 9, 18), date(2026, 9, 19), "18 y 19-09"),
    (date(2026, 10, 12), date(2026, 10, 12), "12-10"),
    (date(2026, 10, 31), date(2026, 11, 1), "31-10 y 01-11"),
]


def x(d, hora=0.0):
    return mdates.date2num(d) + hora / 24.0


def main():
    fig = plt.figure(figsize=(6.5, 3.9), dpi=300)
    ax = fig.add_axes([0.012, 0.215, 0.976, 0.655])
    n = len(FASES)
    ax.set_xlim(x(INICIO) - 0.6, x(FIN))
    ax.set_ylim(n - 0.15, -0.55)
    ax.axis("off")

    # Grilla semanal (lunes) y etiquetas de fecha arriba
    lunes = INICIO
    while lunes <= FIN:
        ax.axvline(x(lunes), color=GRILLA, lw=0.6, zorder=0)
        if lunes < FIN:
            ax.text(
                x(lunes) + 3.5,
                -0.62,
                lunes.strftime("%d-%m"),
                ha="center",
                va="bottom",
                fontsize=7.5,
                color=TINTA_2,
            )
        lunes += timedelta(days=7)

    # Feriados
    for d1, d2, _ in FERIADOS:
        xm = (x(d1) + x(d2 + timedelta(days=1))) / 2
        ax.plot(
            [xm, xm],
            [-0.45, n - 0.25],
            color=FERIADO,
            lw=0.9,
            ls=(0, (1.2, 1.6)),
            zorder=1,
        )

    # Congelamiento del desarrollo: fin del 08-11
    xc = x(date(2026, 11, 9))
    ax.plot([xc, xc], [-0.45, n - 0.25], color="#000000", lw=1.3, zorder=3)

    # Barras de cada fase
    for i, (nombre, d1, d2, color, desc, derecha) in enumerate(FASES):
        x1, x2 = x(d1), x(d2 + timedelta(days=1))
        ax.add_patch(
            Rectangle(
                (x1, i - 0.36),
                x2 - x1,
                0.36,
                facecolor=color,
                edgecolor="white",
                lw=0.8,
                zorder=4,
            )
        )
        ancho_dias = x2 - x1
        caja = dict(
            boxstyle="square,pad=0.08", facecolor="white", edgecolor="none", alpha=1.0
        )
        if ancho_dias >= 7.5 and nombre not in ("Planificación", "Cimientos"):
            ax.text(
                (x1 + x2) / 2 if ancho_dias >= 9 else x1 + 0.5,
                i - 0.18,
                nombre,
                ha="center" if ancho_dias >= 9 else "left",
                va="center",
                fontsize=8,
                color="white",
                fontweight="bold",
                zorder=5,
            )
            texto = desc
            negrita = None
        else:
            # Barra corta: el nombre va en negrita al comienzo de la descripción
            texto = desc
            negrita = nombre + ": "
        xt = x2 if derecha else x1 + 0.3
        ha = "right" if derecha else "left"
        if negrita:
            t1 = ax.text(
                xt,
                i + 0.17,
                negrita,
                ha=ha,
                va="center",
                fontsize=7.5,
                color=TINTA,
                fontweight="bold",
                zorder=7,
                bbox=caja,
            )
            fig.canvas.draw()
            bb = t1.get_window_extent().transformed(ax.transData.inverted())
            ax.text(
                bb.x1,
                i + 0.17,
                texto,
                ha="left",
                va="center",
                fontsize=7.5,
                color=TINTA,
                zorder=7,
                bbox=caja,
            )
        else:
            ax.text(
                xt,
                i + 0.17,
                texto,
                ha=ha,
                va="center",
                fontsize=7.5,
                color=TINTA,
                zorder=7,
                bbox=caja,
            )
        # Sprint 2: siguió abierto en Jira hasta el 23-10
        if nombre == "Sprint 2":
            xa, xb = x(date(2026, 10, 19)), x(date(2026, 10, 23), 11)
            ax.add_patch(
                Rectangle(
                    (xa, i - 0.36),
                    xb - xa,
                    0.36,
                    facecolor="white",
                    edgecolor=color,
                    hatch="////",
                    lw=0.6,
                    zorder=4,
                )
            )

    # Cierres de sprint (triángulos) e hitos (rombos) en la franja de abajo
    yb = n - 0.05
    for d in CIERRES:
        ax.plot(
            x(d + timedelta(days=1)),
            yb,
            marker="v",
            ms=6.5,
            color=AZUL_TITULO,
            zorder=6,
            clip_on=False,
        )
    for d, _ in HITOS:
        ax.plot(
            x(d, 12),
            yb,
            marker="D",
            ms=5.2,
            color="#C55A11",
            mec="white",
            mew=0.8,
            zorder=6,
            clip_on=False,
        )

    fig.text(
        0.5,
        0.965,
        "Cronograma de la replanificación del 25-09: del 07-09 al 12-12-2026",
        ha="center",
        va="top",
        fontsize=10.5,
        color=AZUL_TITULO,
        fontweight="bold",
    )

    # Rótulos de abajo: hitos, feriados y congelamiento (en coordenadas de la figura)
    trans = ax.transData + fig.transFigure.inverted()

    def fx(xd):
        return trans.transform((xd, 0))[0]

    for d, rot in HITOS:
        fig.text(
            fx(x(d, 12)), 0.165, rot, ha="center", va="top", fontsize=7, color="#C55A11"
        )
    for d1, d2, rot in FERIADOS:
        xm = (x(d1) + x(d2 + timedelta(days=1))) / 2
        fig.text(
            fx(xm),
            0.072,
            rot + "\nferiado" + ("s" if d1 != d2 else ""),
            ha="center",
            va="top",
            fontsize=7,
            color=FERIADO,
        )
    # Congelamiento: rótulo arriba de la línea
    ax.text(
        xc + 0.4,
        -0.42,
        "congelamiento del desarrollo, 08-11",
        ha="left",
        va="center",
        fontsize=7,
        color="#000000",
        fontweight="bold",
        zorder=7,
        bbox=dict(boxstyle="square,pad=0.08", facecolor="white", edgecolor="none"),
    )

    # Leyenda, abajo a la derecha
    lx, ly1, ly2 = 0.625, 0.135, 0.075
    fig.text(lx, ly1, "▼", ha="left", va="center", fontsize=8, color=AZUL_TITULO)
    fig.text(
        lx + 0.022,
        ly1,
        "cierre de sprint",
        ha="left",
        va="center",
        fontsize=7.5,
        color=TINTA,
    )
    fig.text(lx + 0.17, ly1, "◆", ha="left", va="center", fontsize=8, color="#C55A11")
    fig.text(lx + 0.192, ly1, "hito", ha="left", va="center", fontsize=7.5, color=TINTA)
    fig.text(lx + 0.26, ly1, "┆", ha="left", va="center", fontsize=8, color=FERIADO)
    fig.text(
        lx + 0.28, ly1, "feriado", ha="left", va="center", fontsize=7.5, color=TINTA
    )
    fig.patches.append(
        Rectangle(
            (lx, ly2 - 0.012),
            0.03,
            0.024,
            transform=fig.transFigure,
            facecolor="white",
            edgecolor="#2E75B6",
            hatch="////",
            lw=0.6,
        )
    )
    fig.text(
        lx + 0.038,
        ly2,
        "Sprint 2 abierto en Jira hasta el 23-10",
        ha="left",
        va="center",
        fontsize=7.5,
        color=TINTA,
    )

    salida = AQUI / "07_cronograma.png"
    fig.savefig(salida, dpi=300, facecolor="white")
    print(salida)


if __name__ == "__main__":
    main()
