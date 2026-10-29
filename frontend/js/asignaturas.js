// Pagina de asignaturas: lee el catalogo real por el gateway (HU-12).
//   GET /api/catalog/v1/carreras                     -> selector de carrera
//   GET /api/catalog/v1/asignaturas?buscar=texto     -> busqueda sin carrera
//   GET /api/catalog/v1/carreras/{id}/asignaturas    -> malla vigente por semestre
//   GET /api/tutoring/v1/tutores?asignatura={id}     -> tutores de una asignatura (HU-40)
// Si la pagina llega con ?buscar=texto (el buscador de la portada), busca eso
// al abrir. Cada tarjeta despliega sus tutores con «Ver tutores»: se piden la
// primera vez que se abre y quedan guardados mientras la pagina siga abierta.
// La peticion a Tutorias va sin la cabecera Authorization, como en tutores.js:
// es un dato publico.
// Los datos se escriben con textContent, nunca con innerHTML, para que un
// nombre con etiquetas no se ejecute como HTML.

const API = "/api/catalog/v1";
const TUTORIAS = "/api/tutoring/v1";

let esperaBusqueda;
let mallaEnMemoria = null; // { carreraId, asignaturas: [...] }
const tutoresPedidos = new Map(); // id de la asignatura -> promesa con sus tutores

document.addEventListener("DOMContentLoaded", () => {
    const buscador = document.getElementById("subjectSearch");
    buscador.value = (new URLSearchParams(window.location.search).get("buscar") || "").trim();

    cargarCarreras();
    cargarAsignaturas();

    buscador.addEventListener("input", () => {
        clearTimeout(esperaBusqueda);
        esperaBusqueda = setTimeout(cargarAsignaturas, 300);
    });
    buscador.addEventListener("keyup", (evento) => {
        if (evento.key === "Enter") {
            clearTimeout(esperaBusqueda);
            cargarAsignaturas();
        }
    });
});

async function pedir(ruta) {
    const respuesta = await fetch(API + ruta, { headers: { Accept: "application/json" } });
    if (!respuesta.ok) {
        throw new Error(`El catálogo respondió ${respuesta.status}`);
    }
    return respuesta.json();
}

// Sin tildes ni mayusculas, para comparar "programacion" con "Programación".
function normalizar(texto) {
    return (texto || "")
        .normalize("NFD")
        .replace(/[̀-ͯ]/g, "")
        .toLowerCase();
}

async function cargarCarreras() {
    const selector = document.getElementById("filter-area");
    try {
        const carreras = await pedir("/carreras");
        carreras.forEach((carrera) => {
            const opcion = document.createElement("option");
            opcion.value = carrera.id;
            opcion.textContent = carrera.nombre;
            selector.appendChild(opcion);
        });
    } catch (error) {
        console.error("No se pudieron cargar las carreras:", error);
    }
}

async function cargarAsignaturas() {
    const texto = document.getElementById("subjectSearch").value.trim();
    const carreraId = document.getElementById("filter-area").value;

    try {
        let asignaturas;
        if (carreraId) {
            // La malla de una carrera es corta: se pide una vez y se filtra aqui.
            if (!mallaEnMemoria || mallaEnMemoria.carreraId !== carreraId) {
                const malla = await pedir(`/carreras/${encodeURIComponent(carreraId)}/asignaturas`);
                mallaEnMemoria = {
                    carreraId,
                    asignaturas: malla.semestres.flatMap((s) =>
                        s.asignaturas.map((a) => ({ ...a, semestre: s.semestre }))
                    ),
                };
            }
            const buscado = normalizar(texto);
            asignaturas = mallaEnMemoria.asignaturas.filter(
                (a) =>
                    !buscado ||
                    normalizar(a.nombre).includes(buscado) ||
                    normalizar(a.sigla).includes(buscado)
            );
        } else {
            mallaEnMemoria = null;
            asignaturas = await pedir(`/asignaturas?buscar=${encodeURIComponent(texto)}`);
        }
        mostrar(asignaturas);
    } catch (error) {
        console.error("No se pudo consultar el catálogo:", error);
        mostrarError();
    }
}

function mostrar(asignaturas) {
    const lista = document.getElementById("subjectsList");
    const contador = document.getElementById("subjectCounter");
    const sinResultados = document.getElementById("noResults");

    lista.replaceChildren(...asignaturas.map(tarjeta));
    const total = asignaturas.length;
    contador.textContent = `${total} ${total === 1 ? "asignatura encontrada" : "asignaturas encontradas"}`;
    sinResultados.style.display = total === 0 ? "block" : "none";
}

function mostrarError() {
    const lista = document.getElementById("subjectsList");
    const aviso = document.createElement("p");
    aviso.style.cssText = "color:#b42318; grid-column:1/-1; text-align:center;";
    aviso.textContent = "No se pudo conectar con el catálogo. Revisa que el sistema esté levantado.";
    lista.replaceChildren(aviso);
    document.getElementById("subjectCounter").textContent = "Sin conexión con el catálogo";
    document.getElementById("noResults").style.display = "none";
}

function elemento(etiqueta, clase, texto) {
    const nodo = document.createElement(etiqueta);
    if (clase) nodo.className = clase;
    if (texto !== undefined) nodo.textContent = texto;
    return nodo;
}

function tarjeta(asignatura) {
    const articulo = elemento("article", "subject-card");

    const cuerpo = elemento("div");
    const cabecera = elemento("div", "subject-card-header");
    const icono = elemento("div", "subject-icon");
    icono.appendChild(elemento("i", "fa-solid fa-book"));
    cabecera.append(icono, elemento("span", "subject-code", asignatura.sigla));
    cuerpo.append(
        cabecera,
        elemento("h3", null, asignatura.nombre),
        elemento(
            "p",
            "subject-area",
            asignatura.semestre ? `Semestre ${asignatura.semestre}` : "Todas las carreras"
        )
    );

    const pie = elemento("div", "subject-card-footer");
    const creditos = elemento("span", "tutor-count");
    creditos.appendChild(elemento("i", "fa-solid fa-layer-group"));
    creditos.append(
        ` ${asignatura.creditos ? `${asignatura.creditos} créditos` : "Créditos sin informar"}`
    );

    // Tutores de la asignatura (HU-40, criterio 1), debajo del pie.
    const idPanel = `tutores-${asignatura.id}`;
    const boton = elemento("button", "ver-tutores");
    boton.type = "button";
    boton.setAttribute("aria-expanded", "false");
    boton.setAttribute("aria-controls", idPanel);
    boton.append(elemento("span", null, "Ver tutores"));
    const flecha = elemento("i", "fa-solid fa-chevron-down");
    flecha.setAttribute("aria-hidden", "true");
    boton.appendChild(flecha);
    pie.append(creditos, boton);

    const panel = elemento("div", "tutores-de-asignatura");
    panel.id = idPanel;
    panel.hidden = true;
    panel.setAttribute("aria-live", "polite");
    boton.addEventListener("click", () => alternarTutores(asignatura, boton, panel));

    articulo.append(cuerpo, pie, panel);
    return articulo;
}

// ------------------------------------------------ tutores de una asignatura

async function alternarTutores(asignatura, boton, panel) {
    const abrir = panel.hidden;
    panel.hidden = !abrir;
    boton.setAttribute("aria-expanded", String(abrir));
    boton.querySelector("span").textContent = abrir ? "Ocultar tutores" : "Ver tutores";
    if (!abrir || panel.dataset.cargado === "si") {
        return;
    }

    panel.replaceChildren(elemento("p", "nota", "Buscando tutores..."));
    try {
        const tutores = await tutoresDe(asignatura.id);
        panel.dataset.cargado = "si";
        if (tutores.length === 0) {
            panel.replaceChildren(
                elemento("p", "nota", "Todavía no hay tutores para esta asignatura.")
            );
            return;
        }
        const lista = elemento("ul");
        lista.setAttribute("aria-label", `Tutores de ${asignatura.nombre}`);
        lista.append(...tutores.map(filaDeTutor));
        panel.replaceChildren(lista);
    } catch (error) {
        // Sin marcarlo como cargado: al volver a abrir se intenta de nuevo.
        console.error("No se pudo consultar Tutorías:", error);
        tutoresPedidos.delete(asignatura.id);
        panel.replaceChildren(
            elemento("p", "nota", "No pudimos cargar los tutores. Inténtalo de nuevo en unos minutos.")
        );
    }
}

function tutoresDe(asignaturaId) {
    if (!tutoresPedidos.has(asignaturaId)) {
        const url = `${TUTORIAS}/tutores?${new URLSearchParams({ asignatura: asignaturaId })}`;
        tutoresPedidos.set(
            asignaturaId,
            fetch(url, { headers: { Accept: "application/json" } }).then((respuesta) => {
                if (!respuesta.ok) {
                    throw new Error(`Tutorías respondió ${respuesta.status}`);
                }
                return respuesta.json();
            })
        );
    }
    return tutoresPedidos.get(asignaturaId);
}

// Un tutor: su nombre con el enlace al perfil, su evaluación y su tarifa.
function filaDeTutor(tutor) {
    const fila = elemento("li", "tutor-de-asignatura");
    const datos = elemento("div");
    const enlace = elemento("a", null, `${tutor.nombre} ${tutor.apellido}`);
    enlace.href = `tutor.html?${new URLSearchParams({ id: tutor.usuario_id })}`;

    const detalle = elemento("span", "detalle");
    const reputacion = tutor.reputacion;
    if (reputacion && reputacion.total > 0) {
        const estrella = elemento("i", "fa-solid fa-star");
        estrella.setAttribute("aria-hidden", "true");
        const promedio = Number(reputacion.promedio).toLocaleString("es-CL", {
            minimumFractionDigits: 1,
            maximumFractionDigits: 1,
        });
        detalle.append(estrella, ` ${promedio} (${reputacion.total})`);
    } else {
        detalle.textContent = "Sin evaluaciones";
    }
    datos.append(enlace, detalle);
    fila.append(datos, elemento("strong", null, tarifaEnTexto(tutor.tarifa)));
    return fila;
}

// "Gratis" si es 0; si no, en pesos con el separador de miles chileno: $5.000.
function tarifaEnTexto(tarifa) {
    const monto = Math.round(Number(tarifa));
    if (monto === 0) {
        return "Gratis";
    }
    return `$${String(monto).replace(/\B(?=(\d{3})+(?!\d))/g, ".")}`;
}
