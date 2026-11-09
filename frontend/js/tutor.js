// Perfil publico de un tutor (HU-18, criterio 3) con la API de Tutorias (HU-20),
// y desde el, la solicitud de una tutoria (HU-21):
//   GET  /api/tutoring/v1/tutores/{id}      -> reputacion, asignaturas, bloques y evaluaciones
//   GET  /api/catalog/v1/carreras y /sedes  -> nombres de carrera y sede, una vez
//   POST /api/tutoring/v1/reservas          -> la solicitud, con el token de acceso
// El id llega en la direccion: tutor.html?id=<usuario_id>, desde la busqueda.
// Las fechas llegan en UTC y se muestran en hora de Chile (America/Santiago).
//
// La peticion del perfil va sin la cabecera Authorization, a proposito: es un
// dato publico, y desde HU-17 Tutorias autentica en todas sus rutas, asi que un
// token vencido o invalido haria responder 401 tambien a este perfil.
//
// Quien tiene la sesion sale de Sesion.yo(), que se pide al abrir la pagina, a
// la vez que el encabezado: sesion.js comparte la renovacion en curso, asi que
// las dos llamadas hacen un solo /refresh. Si POST /reservas responde 401 (el
// token dura 30 minutos), se renueva una vez con Sesion.renovar() y se
// reintenta, como en disponibilidad.js.
//
// Las paginas cargan scripts clasicos, que comparten los nombres globales: aqui
// no se declara ninguno de sesion.js (Sesion, IDENTIDAD, mensajeDeError, avisar,
// mostrarSesionEnEncabezado, activarMenuMovil). Los datos se escriben con
// textContent y nodos de createElement, nunca con innerHTML.

const CATALOGO = "/api/catalog/v1";
const TUTORIAS = "/api/tutoring/v1";
const ZONA_CHILE = "America/Santiago";
const FORMATO_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// La API manda como maximo 10 evaluaciones, las mas nuevas.
const MAXIMO_EVALUACIONES = 10;
// La nota de una solicitud: hasta 500 caracteres (HU-21).
const LARGO_NOTA = 500;

document.addEventListener("DOMContentLoaded", () => {
    prepararVolver();
    // Junto con el encabezado (sesion.js), para compartir la misma renovacion.
    const sesion = usuarioConSesion();
    cargarPerfil(sesion);
});

// El usuario de la sesion, o null si no hay sesion o Identidad no responde.
async function usuarioConSesion() {
    try {
        return await Sesion.yo();
    } catch {
        return null;
    }
}

async function pedir(url) {
    // Sin cabecera Authorization: ver el comentario del principio.
    const respuesta = await fetch(url, { headers: { Accept: "application/json" } });
    if (!respuesta.ok) {
        const error = new Error(`${url} respondió ${respuesta.status}`);
        error.estado = respuesta.status;
        throw error;
    }
    return respuesta.json();
}

// Si se llego desde la busqueda, "Volver" lleva a esa misma busqueda, con lo
// que se habia escrito y la asignatura elegida. De la pagina anterior se usa
// solo la consulta (?buscar=...&asignatura=...), no su ruta: una ruta que
// empieza con // llevaria a otro sitio.
function prepararVolver() {
    try {
        const anterior = new URL(document.referrer);
        // Vuelve a la busqueda de donde vino: tutores.html o asignaturas.html.
        const pagina = anterior.pathname.split("/").pop();
        if (
            anterior.origin === window.location.origin &&
            (pagina === "tutores.html" || pagina === "asignaturas.html")
        ) {
            document.getElementById("enlaceVolver").href = `${pagina}${anterior.search}`;
        }
    } catch {
        // Sin pagina anterior: queda el enlace a tutores.html.
    }
}

async function cargarPerfil(sesion) {
    const id = new URLSearchParams(window.location.search).get("id") || "";
    if (!FORMATO_UUID.test(id)) {
        mostrarAviso(
            "fa-user-slash",
            "No encontramos a este tutor",
            "El enlace no es válido. Vuelve a la búsqueda y abre el perfil desde los resultados."
        );
        return;
    }

    const nombres = nombresDelCatalogo(); // en paralelo con el perfil
    let perfil;
    try {
        perfil = await pedir(`${TUTORIAS}/tutores/${encodeURIComponent(id)}`);
    } catch (error) {
        console.error("No se pudo cargar el perfil:", error);
        if (error.estado === 404) {
            mostrarAviso(
                "fa-user-slash",
                "No encontramos a este tutor",
                "Puede que ya no ofrezca tutorías o que su cuenta esté desactivada."
            );
        } else {
            mostrarAviso(
                "fa-triangle-exclamation",
                "No pudimos cargar el perfil",
                "El servicio de tutorías no respondió. Inténtalo de nuevo en unos minutos."
            );
        }
        return;
    }
    mostrarPerfil(perfil, await nombres);
    prepararSolicitud(perfil, await sesion);
}

// Carreras y sedes se piden una vez. Si Catalogo no responde, el perfil igual
// se muestra, con "sin informar" en lugar del nombre.
async function nombresDelCatalogo() {
    try {
        const [carreras, sedes] = await Promise.all([
            pedir(`${CATALOGO}/carreras`),
            pedir(`${CATALOGO}/sedes`),
        ]);
        return {
            carreras: new Map(carreras.map((carrera) => [carrera.id, carrera.nombre])),
            sedes: new Map(sedes.map((sede) => [sede.id, sede.nombre])),
        };
    } catch (error) {
        console.error("No se pudieron cargar las carreras y las sedes:", error);
        return { carreras: new Map(), sedes: new Map() };
    }
}

function mostrarPerfil(perfil, nombres) {
    const nombreCompleto = `${perfil.nombre} ${perfil.apellido}`;
    document.title = `${nombreCompleto} | Tutorías Duoc UC`;

    document.getElementById("iniciales").textContent = iniciales(perfil);
    document.getElementById("nombreTutor").textContent = nombreCompleto;
    document.getElementById("carreraTutor").textContent =
        nombres.carreras.get(perfil.carrera_id) || "Carrera sin informar";
    document.getElementById("sedeTutor").textContent =
        nombres.sedes.get(perfil.sede_id) || "Sede sin informar";
    document
        .getElementById("reputacionTutor")
        .replaceChildren(...partesDeReputacion(perfil.reputacion));

    llenarLista("etiquetasTutor", perfil.asignaturas.map(etiquetaDeAsignatura), null);
    llenarLista("listaAsignaturas", perfil.asignaturas.map(asignaturaDelPerfil), null);
    llenarLista("listaBloques", perfil.bloques.map(bloqueDisponible), "sinBloques");
    llenarLista("listaEvaluaciones", perfil.evaluaciones.map(evaluacionVisible), "sinEvaluaciones");
    document
        .getElementById("notaEvaluaciones")
        .classList.toggle("hidden", perfil.evaluaciones.length < MAXIMO_EVALUACIONES);

    document.getElementById("cargando").classList.add("hidden");
    document.getElementById("cabeceraPerfil").classList.remove("hidden");
    document.getElementById("cuerpoPerfil").classList.remove("hidden");
}

function llenarLista(idLista, filas, idVacio) {
    document.getElementById(idLista).replaceChildren(...filas);
    if (idVacio) {
        document.getElementById(idVacio).classList.toggle("hidden", filas.length > 0);
    }
}

// "5,0 (1 evaluación)", o "Sin evaluaciones" si todavia no tiene.
function partesDeReputacion(reputacion) {
    if (!reputacion || reputacion.total === 0) {
        return [icono("fa-regular fa-star"), elemento("span", null, "Sin evaluaciones")];
    }
    return [
        icono("fa-solid fa-star"),
        elemento("strong", null, decimal(reputacion.promedio)),
        elemento("span", null, `(${cantidad(reputacion.total, "evaluación", "evaluaciones")})`),
    ];
}

// Etiqueta con la sigla y el nombre, bajo el nombre del tutor.
function etiquetaDeAsignatura(asignatura) {
    const etiqueta = elemento("li");
    etiqueta.append(
        elemento("span", "etiqueta-sigla", asignatura.sigla),
        elemento("span", null, asignatura.nombre)
    );
    return etiqueta;
}

function asignaturaDelPerfil(asignatura) {
    const fila = elemento("li", "perfil-asignatura");
    const cabecera = elemento("div", "perfil-asignatura-cabecera");
    cabecera.append(
        elemento("span", "busqueda-sigla", asignatura.sigla),
        elemento("strong", null, asignatura.nombre)
    );
    fila.append(cabecera, elemento("span", "perfil-tarifa", tarifaEnTexto(asignatura.tarifa)));
    if (asignatura.descripcion) {
        fila.appendChild(elemento("p", "perfil-descripcion", asignatura.descripcion));
    }
    return fila;
}

// Un bloque en hora de Chile: "Viernes, 23 de octubre" y "17:00 a 18:00".
function bloqueDisponible(bloque) {
    const inicio = new Date(bloque.inicio_en);
    const fin = new Date(bloque.fin_en);

    const fila = elemento("li", "perfil-bloque");
    const textos = elemento("div");
    textos.append(
        elemento("strong", null, diaEnChile(inicio)),
        elemento("span", null, `${hora(inicio)} a ${hora(fin)}`)
    );
    fila.append(icono("fa-regular fa-calendar"), textos);
    return fila;
}

function evaluacionVisible(evaluacion) {
    const fila = elemento("li", "perfil-evaluacion");

    const cabecera = elemento("div", "perfil-evaluacion-cabecera");
    const estrellas = elemento("span", "perfil-estrellas");
    estrellas.setAttribute("role", "img");
    estrellas.setAttribute("aria-label", `Calificación ${evaluacion.calificacion} de 5`);
    for (let numero = 1; numero <= 5; numero++) {
        estrellas.appendChild(
            icono(numero <= evaluacion.calificacion ? "fa-solid fa-star" : "fa-regular fa-star")
        );
    }
    const fecha = new Date(evaluacion.creada_en).toLocaleString("es-CL", {
        timeZone: ZONA_CHILE,
        day: "numeric",
        month: "long",
        year: "numeric",
    });
    cabecera.append(estrellas, elemento("span", "perfil-fecha", fecha));

    const comentario = evaluacion.comentario
        ? elemento("p", "perfil-comentario", evaluacion.comentario)
        : elemento("p", "perfil-comentario perfil-sin-comentario", "Sin comentario.");
    const asignatura = evaluacion.asignatura;
    fila.append(
        cabecera,
        comentario,
        elemento(
            "span",
            "perfil-evaluacion-asignatura",
            `${asignatura.sigla} · ${asignatura.nombre}`
        )
    );
    return fila;
}

function mostrarAviso(claseIcono, titulo, texto) {
    document.getElementById("cargando").classList.add("hidden");
    document.getElementById("avisoPerfil").replaceChildren(
        icono(`fa-solid ${claseIcono}`),
        elemento("h3", null, titulo),
        elemento("p", null, texto)
    );
    document.getElementById("avisoPerfil").classList.remove("hidden");
}

// ------------------------------------------------ solicitar una tutoria (HU-21)

// Una sola de las partes de #solicitud, segun quien mira: sin sesion, el
// enlace para iniciarla; el propio tutor, el aviso de que es su perfil; si el
// tutor no tiene horarios disponibles, ninguna (basta el aviso de "Horarios
// disponibles"); si no, el formulario.
function prepararSolicitud(perfil, usuario) {
    if (!usuario) {
        mostrarParteDeSolicitud("solicitudSinSesion");
        return;
    }
    if (String(usuario.id).toLowerCase() === String(perfil.usuario_id).toLowerCase()) {
        mostrarParteDeSolicitud("solicitudPropia");
        return;
    }
    if (perfil.bloques.length === 0) {
        return;
    }

    // Los mismos bloques que muestra el perfil, en hora de Chile.
    document
        .getElementById("bloqueSolicitud")
        .replaceChildren(
            opcion("", "Elige un horario"),
            ...perfil.bloques.map((bloque) => opcion(bloque.id, textoDelBloque(bloque)))
        );

    // Cada asignatura con su tarifa a la vista. Si ensena una sola, ya va elegida.
    const asignaturas = perfil.asignaturas.map((asignatura) =>
        opcion(
            asignatura.asignatura_id,
            `${asignatura.sigla} · ${asignatura.nombre} · ${tarifaEnTexto(asignatura.tarifa)}`
        )
    );
    const selector = document.getElementById("asignaturaSolicitud");
    if (asignaturas.length === 1) {
        selector.replaceChildren(...asignaturas);
    } else {
        selector.replaceChildren(opcion("", "Elige una asignatura"), ...asignaturas);
    }
    selector.addEventListener("change", () => mostrarTarifaElegida(perfil.asignaturas));
    mostrarTarifaElegida(perfil.asignaturas);

    document.getElementById("notaTutoria").addEventListener("input", contarNota);
    contarNota();
    document.getElementById("formSolicitud").addEventListener("submit", enviarSolicitud);
    mostrarParteDeSolicitud("formSolicitud");
}

function mostrarParteDeSolicitud(id) {
    document.getElementById(id).classList.remove("hidden");
    document.getElementById("solicitud").classList.remove("hidden");
}

// "Tarifa: $5.000" o "Tarifa: Gratis", bajo la asignatura elegida.
function mostrarTarifaElegida(asignaturas) {
    const elegida = document.getElementById("asignaturaSolicitud").value;
    const asignatura = asignaturas.find((a) => a.asignatura_id === elegida);
    const ayuda = document.getElementById("tarifaSolicitud");
    ayuda.textContent = asignatura ? `Tarifa: ${tarifaEnTexto(asignatura.tarifa)}` : "";
    ayuda.classList.toggle("hidden", !asignatura);
}

function contarNota() {
    const largo = document.getElementById("notaTutoria").value.length;
    document.getElementById("contadorNota").textContent = `${largo}/${LARGO_NOTA}`;
}

async function enviarSolicitud(evento) {
    evento.preventDefault();
    const bloqueId = document.getElementById("bloqueSolicitud").value;
    const asignaturaId = document.getElementById("asignaturaSolicitud").value;
    if (!bloqueId) {
        avisarSolicitud("error", "Elige uno de los horarios disponibles del tutor.");
        return;
    }
    if (!asignaturaId) {
        avisarSolicitud("error", "Elige la asignatura de la tutoría.");
        return;
    }

    const nota = document.getElementById("notaTutoria");
    const boton = document.getElementById("botonSolicitar");
    boton.disabled = true;
    try {
        const r = await pedirReserva(
            JSON.stringify({ bloque_id: bloqueId, asignatura_id: asignaturaId, nota: nota.value })
        );
        if (r.ok) {
            nota.value = "";
            contarNota();
            avisarSolicitud(
                "success",
                "Solicitud enviada. Queda pendiente hasta que el tutor la confirme o la rechace."
            );
        } else if (r.estado === 401) {
            avisarSolicitud(
                "error",
                "Tu sesión venció. Vuelve a iniciar sesión para enviar la solicitud."
            );
        } else {
            avisarSolicitud(
                "error",
                mensajeDeError(r.cuerpo, "No se pudo enviar la solicitud. Inténtalo de nuevo.")
            );
        }
    } catch {
        avisarSolicitud(
            "error",
            "No hay conexión con el servicio de Tutorías. Inténtalo de nuevo en unos minutos."
        );
    } finally {
        boton.disabled = false;
    }
}

// POST /reservas con el token de acceso. Si vencio (dura 30 minutos), se
// renueva una vez con la cookie y se reintenta, como en disponibilidad.js.
async function pedirReserva(cuerpo) {
    const enviar = () =>
        fetch(`${TUTORIAS}/reservas`, {
            method: "POST",
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
                Authorization: `Bearer ${Sesion.tokenAcceso}`,
            },
            body: cuerpo,
        });
    let respuesta = await enviar();
    if (respuesta.status === 401 && (await Sesion.renovar())) {
        respuesta = await enviar();
    }
    let datos = null;
    try {
        datos = await respuesta.json();
    } catch {
        datos = null;
    }
    return { ok: respuesta.ok, estado: respuesta.status, cuerpo: datos };
}

// Con avisar() de sesion.js. En el telefono la caja puede quedar fuera de la
// pantalla: se lleva a la vista.
function avisarSolicitud(tipo, texto) {
    const caja = document.getElementById("mensajeSolicitud");
    avisar(caja, tipo, texto);
    caja.scrollIntoView({ block: "nearest" });
}

// ------------------------------------------------ utilidades

// "Viernes, 23 de octubre": el dia de un instante, en hora de Chile.
function diaEnChile(fecha) {
    return conMayuscula(
        fecha.toLocaleString("es-CL", {
            timeZone: ZONA_CHILE,
            weekday: "long",
            day: "numeric",
            month: "long",
        })
    );
}

// Un bloque en una linea, para el selector: "Vie, 23 oct · 17:00 a 18:00".
// Va corto para que el selector cerrado muestre la hora completa.
function textoDelBloque(bloque) {
    const inicio = new Date(bloque.inicio_en);
    const dia = conMayuscula(
        inicio.toLocaleString("es-CL", {
            timeZone: ZONA_CHILE,
            weekday: "short",
            day: "numeric",
            month: "short",
        })
    );
    return `${dia} · ${hora(inicio)} a ${hora(new Date(bloque.fin_en))}`;
}

function opcion(valor, texto) {
    const nodo = document.createElement("option");
    nodo.value = valor;
    nodo.textContent = texto;
    return nodo;
}

function hora(fecha) {
    return fecha.toLocaleString("es-CL", {
        timeZone: ZONA_CHILE,
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23", // 17:00, no 05:00 p. m.
    });
}

function conMayuscula(texto) {
    return texto.charAt(0).toUpperCase() + texto.slice(1);
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
