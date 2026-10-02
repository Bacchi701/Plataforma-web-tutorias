// Pagina de asignaturas: lee el catalogo real por el gateway (HU-12).
//   GET /api/catalog/v1/carreras                     -> selector de carrera
//   GET /api/catalog/v1/asignaturas?buscar=texto     -> busqueda sin carrera
//   GET /api/catalog/v1/carreras/{id}/asignaturas    -> malla vigente por semestre
// Los datos se escriben con textContent, nunca con innerHTML, para que un
// nombre con etiquetas no se ejecute como HTML.

const API = "/api/catalog/v1";

let esperaBusqueda;
let mallaEnMemoria = null; // { carreraId, asignaturas: [...] }

document.addEventListener("DOMContentLoaded", () => {
    cargarCarreras();
    cargarAsignaturas();

    const buscador = document.getElementById("subjectSearch");
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
    pie.appendChild(creditos);

    articulo.append(cuerpo, pie);
    return articulo;
}
