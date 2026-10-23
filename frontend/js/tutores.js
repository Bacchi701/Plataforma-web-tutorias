// Busqueda de tutores (HU-18) sobre las API reales, por el gateway:
//   GET /api/catalog/v1/asignaturas?buscar=texto   -> asignaturas que coinciden (HU-12)
//   GET /api/tutoring/v1/tutores?asignatura={id}   -> tutores de la elegida (HU-20)
//   GET /api/catalog/v1/carreras y /sedes          -> nombres de carrera y sede, una vez
// Si la pagina llega con ?buscar=texto (el buscador de la portada), busca eso
// al abrir. Lo buscado y la asignatura elegida quedan en la direccion, para que
// al volver desde el perfil del tutor se vea lo mismo.
//
// Las peticiones a Tutorias van sin la cabecera Authorization, a proposito: son
// datos publicos, y desde HU-17 Tutorias autentica en todas sus rutas, asi que
// un token vencido o invalido haria responder 401 tambien a esta busqueda.
// Tampoco se llama a Sesion.yo() ni a Sesion.renovar(): el encabezado
// (sesion.js) ya renueva la sesion al abrir la pagina, y dos renovaciones a la
// vez con la misma cookie dejarian a una de las dos sin sesion.
//
// Los datos se escriben con textContent y nodos de createElement, nunca con
// innerHTML, para que un nombre con etiquetas no se ejecute como HTML.

const CATALOGO = "/api/catalog/v1";
const TUTORIAS = "/api/tutoring/v1";

let esperaBusqueda;
// Cada busqueda y cada eleccion lleva un numero: si llega la respuesta de una
// anterior, despues de que el usuario cambio lo que buscaba, se descarta.
let ultimaBusqueda = 0;
let ultimaEleccion = 0;
let textoDeLaLista = ""; // lo que se busco para la lista que esta en pantalla
let nombresCatalogo = null; // promesa con { carreras, sedes }: Map de id a nombre

document.addEventListener("DOMContentLoaded", () => {
    const formulario = document.getElementById("formularioBusqueda");
    const caja = document.getElementById("textoBusqueda");

    caja.addEventListener("input", () => {
        clearTimeout(esperaBusqueda);
        esperaBusqueda = setTimeout(() => buscarAsignaturas(caja.value), 300);
    });
    formulario.addEventListener("submit", (evento) => {
        evento.preventDefault();
        clearTimeout(esperaBusqueda);
        buscarAsignaturas(caja.value);
    });

    nombresDelCatalogo(); // se piden de inmediato, para tenerlos al elegir

    const parametros = new URLSearchParams(window.location.search);
    const texto = (parametros.get("buscar") || "").trim();
    if (texto) {
        caja.value = texto;
        buscarAsignaturas(texto, parametros.get("asignatura"));
    }
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

// ------------------------------------------------ paso 1: las asignaturas

async function buscarAsignaturas(textoEscrito, idPorElegir = null) {
    const texto = textoEscrito.trim();
    const numero = ++ultimaBusqueda;
    const lista = document.getElementById("listaAsignaturas");
    const contador = document.getElementById("contadorAsignaturas");

    ocultarTutores();
    if (!texto) {
        textoDeLaLista = "";
        guardarEnDireccion("", null);
        lista.replaceChildren();
        contador.textContent = "";
        mostrarAviso(
            "avisoAsignaturas",
            "fa-magnifying-glass",
            "Empieza por la asignatura",
            "Escribe parte del nombre o de la sigla para ver las asignaturas que coinciden."
        );
        return;
    }

    contador.textContent = "Buscando...";
    let asignaturas;
    try {
        asignaturas = await pedir(`${CATALOGO}/asignaturas?buscar=${encodeURIComponent(texto)}`);
    } catch (error) {
        if (numero !== ultimaBusqueda) {
            return;
        }
        console.error("No se pudo consultar el catálogo:", error);
        lista.replaceChildren();
        contador.textContent = "";
        mostrarAviso(
            "avisoAsignaturas",
            "fa-triangle-exclamation",
            "No pudimos buscar asignaturas",
            "El catálogo no respondió. Revisa tu conexión e inténtalo de nuevo en unos minutos."
        );
        return;
    }
    if (numero !== ultimaBusqueda) {
        return; // mientras tanto el usuario escribio otra cosa
    }

    textoDeLaLista = texto;
    guardarEnDireccion(texto, null);
    lista.replaceChildren(...asignaturas.map(botonDeAsignatura));
    contador.textContent = cantidad(asignaturas.length, "asignatura", "asignaturas");
    if (asignaturas.length === 0) {
        mostrarAviso(
            "avisoAsignaturas",
            "fa-magnifying-glass",
            "No encontramos asignaturas",
            `Nada coincide con «${texto}». Prueba con otra parte del nombre o con la sigla.`
        );
    } else {
        ocultarAviso("avisoAsignaturas");
    }

    const elegida = asignaturas.find((asignatura) => asignatura.id === idPorElegir);
    if (elegida) {
        elegirAsignatura(elegida);
    }
}

function botonDeAsignatura(asignatura) {
    const boton = elemento("button", "busqueda-asignatura");
    boton.type = "button";
    boton.dataset.id = asignatura.id;
    boton.setAttribute("aria-pressed", "false");
    boton.append(
        elemento("span", "busqueda-sigla", asignatura.sigla),
        elemento("span", "busqueda-nombre", asignatura.nombre)
    );
    boton.addEventListener("click", () => elegirAsignatura(asignatura));
    return boton;
}

// ------------------------------------------------ paso 2: los tutores

async function elegirAsignatura(asignatura) {
    const numero = ++ultimaEleccion;
    const seccion = document.getElementById("seccionTutores");
    const lista = document.getElementById("listaTutores");
    const contador = document.getElementById("contadorTutores");

    document.querySelectorAll(".busqueda-asignatura").forEach((boton) => {
        boton.setAttribute("aria-pressed", String(boton.dataset.id === asignatura.id));
    });
    guardarEnDireccion(textoDeLaLista, asignatura.id);

    document.getElementById("tituloTutores").textContent =
        `Tutores de ${asignatura.nombre} (${asignatura.sigla})`;
    lista.replaceChildren();
    ocultarAviso("avisoTutores");
    contador.textContent = "Buscando tutores...";
    seccion.classList.remove("hidden");
    seccion.scrollIntoView({ behavior: "smooth", block: "start" });

    let tutores;
    let nombres;
    try {
        [tutores, nombres] = await Promise.all([
            pedir(`${TUTORIAS}/tutores?asignatura=${encodeURIComponent(asignatura.id)}`),
            nombresDelCatalogo(),
        ]);
    } catch (error) {
        if (numero !== ultimaEleccion) {
            return;
        }
        console.error("No se pudo consultar Tutorías:", error);
        contador.textContent = "";
        mostrarAviso(
            "avisoTutores",
            "fa-triangle-exclamation",
            "No pudimos cargar los tutores",
            "El servicio de tutorías no respondió. Inténtalo de nuevo en unos minutos."
        );
        return;
    }
    if (numero !== ultimaEleccion) {
        return; // mientras tanto el usuario eligio otra asignatura o busco otra cosa
    }

    contador.textContent = cantidad(tutores.length, "tutor", "tutores");
    if (tutores.length === 0) {
        mostrarAviso(
            "avisoTutores",
            "fa-user-graduate",
            "Todavía no hay tutores para esta asignatura",
            "Prueba con otra asignatura o vuelve a buscar más adelante."
        );
        return;
    }
    lista.replaceChildren(...tutores.map((tutor) => tarjetaDeTutor(tutor, nombres)));
}

function ocultarTutores() {
    ultimaEleccion++; // descarta la respuesta de una eleccion que siga en camino
    document.getElementById("seccionTutores").classList.add("hidden");
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
        elemento("span", null, "Tarifa"),
        elemento("strong", null, tarifaEnTexto(tutor.tarifa))
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
        pie
    );
    return tarjeta;
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

// Deja en la direccion lo buscado y la asignatura elegida, sin recargar.
function guardarEnDireccion(texto, asignaturaId) {
    const parametros = new URLSearchParams();
    if (texto) {
        parametros.set("buscar", texto);
    }
    if (asignaturaId) {
        parametros.set("asignatura", asignaturaId);
    }
    const consulta = parametros.toString();
    history.replaceState(null, "", consulta ? `?${consulta}` : window.location.pathname);
}

function mostrarAviso(id, claseIcono, titulo, texto) {
    const caja = document.getElementById(id);
    caja.replaceChildren(
        icono(`fa-solid ${claseIcono}`),
        elemento("h3", null, titulo),
        elemento("p", null, texto)
    );
    caja.classList.remove("hidden");
}

function ocultarAviso(id) {
    document.getElementById(id).classList.add("hidden");
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
