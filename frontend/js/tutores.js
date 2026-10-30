// Busqueda de tutores por nombre (HU-40), sobre las API reales, por el gateway:
//   GET /api/tutoring/v1/tutores                      -> los mejor evaluados
//   GET /api/tutoring/v1/tutores?buscar=texto         -> los que coinciden con el nombre
//   GET /api/tutoring/v1/tutores?min_reputacion=4     -> solo con 4 estrellas o mas
//   GET /api/catalog/v1/carreras y /sedes             -> nombres de carrera y sede, una vez
// La busqueda por asignatura esta en asignaturas.html: cada asignatura
// despliega sus tutores (HU-40, criterio 1).
// Lo buscado queda en la direccion (?buscar= y ?min_reputacion=), para que al
// volver desde el perfil del tutor se vea lo mismo.
//
// Las peticiones a Tutorias van sin la cabecera Authorization, a proposito: son
// datos publicos, y desde HU-17 Tutorias autentica en todas sus rutas, asi que
// un token vencido o invalido haria responder 401 tambien a esta busqueda.
// Tampoco se llama a Sesion.yo() ni a Sesion.renovar(): el encabezado
// (sesion.js) ya renueva la sesion al abrir la pagina.
//
// Los datos se escriben con textContent y nodos de createElement, nunca con
// innerHTML, para que un nombre con etiquetas no se ejecute como HTML.

const CATALOGO = "/api/catalog/v1";
const TUTORIAS = "/api/tutoring/v1";
// En la tarjeta caben cuatro etiquetas; el resto se cuenta en una quinta.
const MAXIMO_ETIQUETAS = 4;

let esperaBusqueda;
// Cada busqueda lleva un numero: si llega la respuesta de una anterior,
// despues de que el usuario cambio lo que buscaba, se descarta.
let ultimaBusqueda = 0;
let nombresCatalogo = null; // promesa con { carreras, sedes }: Map de id a nombre

document.addEventListener("DOMContentLoaded", () => {
    const formulario = document.getElementById("formularioBusqueda");
    const caja = document.getElementById("textoBusqueda");
    const minimo = document.getElementById("minimoReputacion");

    const parametros = new URLSearchParams(window.location.search);
    caja.value = (parametros.get("buscar") || "").trim();
    const minimoPedido = parametros.get("min_reputacion") || "";
    if ([...minimo.options].some((opcion) => opcion.value === minimoPedido)) {
        minimo.value = minimoPedido;
    }

    caja.addEventListener("input", () => {
        clearTimeout(esperaBusqueda);
        esperaBusqueda = setTimeout(buscarTutores, 300);
    });
    minimo.addEventListener("change", buscarTutores);
    formulario.addEventListener("submit", (evento) => {
        evento.preventDefault();
        clearTimeout(esperaBusqueda);
        buscarTutores();
    });

    buscarTutores();
});

async function pedir(url) {
    // Sin cabecera Authorization: ver el comentario del principio.
    const respuesta = await fetch(url, { headers: { Accept: "application/json" } });
    if (!respuesta.ok) {
        throw new Error(`${url} respondió ${respuesta.status}`);
    }
    return respuesta.json();
}

// Carreras y sedes se piden una sola vez. Si Catalogo no responde, las
// tarjetas igual se muestran, con "sin informar" en lugar del nombre.
function nombresDelCatalogo() {
    if (!nombresCatalogo) {
        nombresCatalogo = Promise.all([
            pedir(`${CATALOGO}/carreras`),
            pedir(`${CATALOGO}/sedes`),
        ])
            .then(([carreras, sedes]) => ({
                carreras: new Map(carreras.map((carrera) => [carrera.id, carrera.nombre])),
                sedes: new Map(sedes.map((sede) => [sede.id, sede.nombre])),
            }))
            .catch((error) => {
                console.error("No se pudieron cargar las carreras y las sedes:", error);
                return { carreras: new Map(), sedes: new Map() };
            });
    }
    return nombresCatalogo;
}

async function buscarTutores() {
    const texto = document.getElementById("textoBusqueda").value.trim();
    const minimo = document.getElementById("minimoReputacion").value;
    const numero = ++ultimaBusqueda;
    const lista = document.getElementById("listaTutores");
    const contador = document.getElementById("contadorTutores");

    guardarEnDireccion(texto, minimo);
    document.getElementById("tituloTutores").textContent = texto
        ? `Tutores que coinciden con «${texto}»`
        : "Tutores mejor evaluados";
    contador.textContent = "Buscando...";
    ocultarAviso();

    const consulta = new URLSearchParams();
    if (texto) {
        consulta.set("buscar", texto);
    }
    if (minimo) {
        consulta.set("min_reputacion", minimo);
    }
    const url = `${TUTORIAS}/tutores${consulta.toString() ? `?${consulta}` : ""}`;

    let tutores;
    let nombres;
    try {
        [tutores, nombres] = await Promise.all([pedir(url), nombresDelCatalogo()]);
    } catch (error) {
        if (numero !== ultimaBusqueda) {
            return;
        }
        console.error("No se pudo consultar Tutorías:", error);
        lista.replaceChildren();
        contador.textContent = "";
        mostrarAviso(
            "fa-triangle-exclamation",
            "No pudimos cargar los tutores",
            "El servicio de tutorías no respondió. Inténtalo de nuevo en unos minutos."
        );
        return;
    }
    if (numero !== ultimaBusqueda) {
        return; // mientras tanto el usuario escribio otra cosa
    }

    lista.replaceChildren(...tutores.map((tutor) => tarjetaDeTutor(tutor, nombres)));
    contador.textContent = cantidad(tutores.length, "tutor", "tutores");
    if (tutores.length === 0) {
        mostrarSinResultados(texto, minimo);
    }
}

// Sin resultados: si se busco un nombre, puede ser una asignatura (los
// enlaces de antes llegaban aqui con ?buscar=asignatura).
function mostrarSinResultados(texto, minimo) {
    if (texto) {
        const enlace = elemento("a", "enlace-texto", "Asignaturas");
        enlace.href = `asignaturas.html?${new URLSearchParams({ buscar: texto })}`;
        const parrafo = elemento("p", null, "Revisa cómo se escribe. Si es una asignatura, búscala en ");
        parrafo.append(enlace, ".");
        mostrarAviso("fa-magnifying-glass", `No encontramos tutores con «${texto}»`, parrafo);
        return;
    }
    if (minimo) {
        mostrarAviso(
            "fa-star",
            "Ningún tutor llega a esa evaluación",
            "Prueba con «Todas las evaluaciones»: los tutores nuevos todavía no tienen evaluaciones."
        );
        return;
    }
    mostrarAviso(
        "fa-user-graduate",
        "Todavía no hay tutores",
        "Cuando un estudiante declare una asignatura que puede enseñar, aparecerá aquí."
    );
}

function tarjetaDeTutor(tutor, nombres) {
    const nombreCompleto = `${tutor.nombre} ${tutor.apellido}`;
    const tarjeta = elemento("article", "tutor-list-card");

    const cabecera = elemento("div", "tutor-header");
    const avatar = elemento("div", "avatar", iniciales(tutor));
    avatar.setAttribute("aria-hidden", "true");
    cabecera.appendChild(avatar);

    const sede = elemento("p", "tarjeta-sede");
    const nombreSede = nombres.sedes.get(tutor.sede_id) || "Sede sin informar";
    sede.append(icono("fa-solid fa-location-dot"), ` ${nombreSede}`);

    const pie = elemento("div", "tutor-footer");
    const precio = elemento("div");
    precio.append(
        elemento("span", null, "Tarifa desde"),
        elemento("strong", null, tarifaEnTexto(tarifaMinima(tutor.asignaturas)))
    );
    const enlace = elemento("a", "tarjeta-perfil", "Ver perfil");
    enlace.href = `tutor.html?${new URLSearchParams({ id: tutor.usuario_id })}`;
    enlace.setAttribute("aria-label", `Ver el perfil de ${nombreCompleto}`);
    pie.append(precio, enlace);

    tarjeta.append(
        cabecera,
        elemento("h3", null, nombreCompleto),
        elemento("p", "career", nombres.carreras.get(tutor.carrera_id) || "Carrera sin informar"),
        sede,
        lineaDeReputacion(tutor.reputacion),
        etiquetasDeAsignaturas(tutor.asignaturas),
        pie
    );
    return tarjeta;
}

function etiquetasDeAsignaturas(asignaturas) {
    const lista = elemento("ul", "tarjeta-etiquetas");
    lista.setAttribute("aria-label", "Asignaturas que imparte");
    asignaturas.slice(0, MAXIMO_ETIQUETAS).forEach((asignatura) => {
        const etiqueta = elemento("li");
        etiqueta.title = `${asignatura.sigla} · ${asignatura.nombre}`;
        etiqueta.textContent = asignatura.nombre;
        lista.appendChild(etiqueta);
    });
    const restantes = asignaturas.length - MAXIMO_ETIQUETAS;
    if (restantes > 0) {
        lista.appendChild(elemento("li", "etiqueta-mas", `+${restantes} más`));
    }
    return lista;
}

function tarifaMinima(asignaturas) {
    return Math.min(...asignaturas.map((asignatura) => Number(asignatura.tarifa)));
}

// Promedio con una estrella y la cantidad de evaluaciones: "5,0 (1)".
function lineaDeReputacion(reputacion) {
    const linea = elemento("div", "rating");
    if (!reputacion || reputacion.total === 0) {
        linea.append(icono("fa-regular fa-star"), elemento("span", null, "Sin evaluaciones"));
        return linea;
    }
    const promedio = decimal(reputacion.promedio);
    const evaluaciones = cantidad(reputacion.total, "evaluación", "evaluaciones");
    linea.title = `Promedio ${promedio} de 5, con ${evaluaciones}`;
    linea.append(
        icono("fa-solid fa-star"),
        elemento("strong", null, promedio),
        elemento("span", null, `(${reputacion.total})`)
    );
    return linea;
}

// ------------------------------------------------ utilidades

// Deja en la direccion lo buscado, sin recargar.
function guardarEnDireccion(texto, minimo) {
    const parametros = new URLSearchParams();
    if (texto) {
        parametros.set("buscar", texto);
    }
    if (minimo) {
        parametros.set("min_reputacion", minimo);
    }
    const consulta = parametros.toString();
    history.replaceState(null, "", consulta ? `?${consulta}` : window.location.pathname);
}

// texto puede ser un texto o un nodo ya armado.
function mostrarAviso(claseIcono, titulo, texto) {
    const caja = document.getElementById("avisoTutores");
    const cuerpo = typeof texto === "string" ? elemento("p", null, texto) : texto;
    caja.replaceChildren(icono(`fa-solid ${claseIcono}`), elemento("h3", null, titulo), cuerpo);
    caja.classList.remove("hidden");
}

function ocultarAviso() {
    document.getElementById("avisoTutores").classList.add("hidden");
}

function elemento(etiqueta, clase, texto) {
    const nodo = document.createElement(etiqueta);
    if (clase) nodo.className = clase;
    if (texto !== undefined) nodo.textContent = texto;
    return nodo;
}

function icono(clases) {
    const nodo = elemento("i", clases);
    nodo.setAttribute("aria-hidden", "true");
    return nodo;
}

function iniciales(persona) {
    const primera = (texto) => Array.from(texto || "")[0] || "";
    return (primera(persona.nombre) + primera(persona.apellido)).toUpperCase();
}

// "Gratis" si es 0; si no, en pesos con el separador de miles chileno: $5.000.
// El punto se pone a mano, porque no todos los navegadores lo ponen en los
// numeros de cuatro cifras.
function tarifaEnTexto(tarifa) {
    const monto = Math.round(Number(tarifa));
    if (monto === 0) {
        return "Gratis";
    }
    return `$${String(monto).replace(/\B(?=(\d{3})+(?!\d))/g, ".")}`;
}

// Un decimal y coma, como se escribe en Chile: 4,5.
function decimal(numero) {
    return Number(numero).toLocaleString("es-CL", {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
    });
}

function cantidad(numero, singular, plural) {
    return `${numero} ${numero === 1 ? singular : plural}`;
}
