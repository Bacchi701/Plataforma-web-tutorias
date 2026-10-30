// Pagina "Mi perfil" (HU-10): nombre, carrera, sede y nivel del usuario.
//   GET   /api/identity/v1/yo        -> datos de la cuenta (Sesion.yo)
//   PATCH /api/identity/v1/yo        -> guarda el perfil con el token de acceso
//   GET   /api/catalog/v1/carreras   -> opciones de carrera
//   GET   /api/catalog/v1/sedes      -> opciones de sede
// El correo se muestra, pero no se envia: no se puede cambiar (criterio 5).
// Los datos se escriben con textContent o value, nunca con innerHTML.

const CATALOGO = "/api/catalog/v1";
const NIVEL_MAXIMO = 12;

// El encabezado (sesion.js) y esta pagina piden la sesion al mismo tiempo: la
// renovacion se comparte en Sesion.renovar (sesion.js).

document.addEventListener("DOMContentLoaded", () => {
    llenarNiveles();
    document.getElementById("profileForm").addEventListener("submit", guardarPerfil);
    cargarPerfil();
});

// Avisa con avisar() de sesion.js. En el telefono el aviso puede quedar
// arriba, fuera de la pantalla: se lleva a la vista.
function avisarEnPerfil(tipo, texto) {
    const caja = document.getElementById("profileMessage");
    avisar(caja, tipo, texto);
    caja.scrollIntoView({ block: "nearest" });
}

function opcion(valor, texto) {
    const nodo = document.createElement("option");
    nodo.value = valor;
    nodo.textContent = texto;
    return nodo;
}

function llenarNiveles() {
    const selector = document.getElementById("nivel");
    for (let nivel = 1; nivel <= NIVEL_MAXIMO; nivel += 1) {
        selector.appendChild(opcion(String(nivel), `Semestre ${nivel}`));
    }
}

function llenarSelector(id, elementos) {
    const selector = document.getElementById(id);
    elementos.forEach((elemento) => selector.appendChild(opcion(elemento.id, elemento.nombre)));
}

async function pedirCatalogo(ruta) {
    const respuesta = await fetch(CATALOGO + ruta, { headers: { Accept: "application/json" } });
    if (!respuesta.ok) {
        throw new Error(`El catálogo respondió ${respuesta.status}`);
    }
    return respuesta.json();
}

async function cargarPerfil() {
    // Las listas del catalogo se piden mientras se recupera la sesion.
    const listas = Promise.all([pedirCatalogo("/carreras"), pedirCatalogo("/sedes")]).catch(
        (error) => {
            console.error("No se pudieron cargar las carreras y sedes:", error);
            return null;
        }
    );

    let usuario;
    try {
        usuario = await Sesion.yo();
    } catch {
        mostrarSinConexion();
        return;
    }
    if (!usuario) {
        mostrarSinSesion("Tu perfil es privado: entra con tu cuenta para verlo y completarlo.");
        return;
    }

    const opciones = await listas;
    if (opciones) {
        llenarSelector("carrera", opciones[0]);
        llenarSelector("sede", opciones[1]);
    }
    mostrarPerfil(usuario);
    document.getElementById("profileLoading").classList.add("hidden");
    document.getElementById("profileForm").classList.remove("hidden");

    if (!opciones) {
        document.getElementById("profileSave").disabled = true;
        avisarEnPerfil(
            "error",
            "No se pudieron cargar las carreras y sedes del catálogo. Revisa que el sistema esté levantado y recarga la página."
        );
    }
}

// Elige la opcion guardada. Si ya no esta en la lista del catalogo, el
// selector queda en "Elige ...".
function elegir(id, valor) {
    const selector = document.getElementById(id);
    selector.value = valor;
    if (selector.value !== valor) {
        selector.value = "";
    }
}

function mostrarPerfil(usuario) {
    document.getElementById("email").value = usuario.email;
    document.getElementById("nombre").value = usuario.nombre;
    document.getElementById("apellido").value = usuario.apellido;
    elegir("carrera", usuario.carrera_id || "");
    elegir("sede", usuario.sede_id || "");
    elegir("nivel", usuario.nivel ? String(usuario.nivel) : "");
    mostrarEstado(usuario);
}

// Criterio 1: con el perfil incompleto se dice que falta.
function mostrarEstado(usuario) {
    const faltan = [];
    if (!usuario.carrera_id) {
        faltan.push("tu carrera");
    }
    if (!usuario.sede_id) {
        faltan.push("tu sede");
    }
    if (!usuario.nivel) {
        faltan.push("tu nivel");
    }
    const estado = document.getElementById("profileStatus");
    estado.classList.toggle("hidden", faltan.length === 0);
    if (faltan.length) {
        const ultimo = faltan[faltan.length - 1];
        const lista =
            faltan.length === 1 ? ultimo : `${faltan.slice(0, -1).join(", ")} y ${ultimo}`;
        estado.textContent = `Tu perfil está incompleto: elige ${lista} para poder ofrecer tutorías.`;
    }
}

function mostrarSinSesion(texto) {
    document.getElementById("profileLoading").classList.add("hidden");
    document.getElementById("profileForm").classList.add("hidden");
    document.getElementById("profileNoSessionText").textContent = texto;
    document.getElementById("profileNoSession").classList.remove("hidden");
}

function mostrarSinConexion() {
    const cargando = document.getElementById("profileLoading");
    cargando.textContent =
        "No hay conexión con el servicio de Identidad. Revisa que el sistema esté levantado y recarga la página.";
    cargando.classList.add("profile-error");
}

// Mismos mensajes que devuelve PATCH /yo (criterio 3).
function problemaAntesDeGuardar(datos) {
    if (!datos.nombre) {
        return { campo: "nombre", mensaje: "Escribe tu nombre." };
    }
    if (!datos.apellido) {
        return { campo: "apellido", mensaje: "Escribe tu apellido." };
    }
    if (!datos.carrera_id) {
        return { campo: "carrera", mensaje: "Elige tu carrera." };
    }
    if (!datos.sede_id) {
        return { campo: "sede", mensaje: "Elige tu sede." };
    }
    if (!Number.isInteger(datos.nivel) || datos.nivel < 1 || datos.nivel > NIVEL_MAXIMO) {
        return { campo: "nivel", mensaje: "Elige tu nivel, de 1 a 12." };
    }
    return null;
}

// PATCH con el token de acceso. Si vencio (dura 30 minutos), se renueva una
// vez con la cookie y se reintenta.
async function enviarPerfil(datos) {
    const enviar = () =>
        Sesion.pedir("/yo", {
            method: "PATCH",
            headers: { Authorization: `Bearer ${Sesion.tokenAcceso}` },
            body: JSON.stringify(datos),
        });
    let r = await enviar();
    if (r.estado === 401 && (await Sesion.renovar())) {
        r = await enviar();
    }
    return r;
}

async function guardarPerfil(evento) {
    evento.preventDefault();
    const datos = {
        nombre: document.getElementById("nombre").value.trim(),
        apellido: document.getElementById("apellido").value.trim(),
        carrera_id: document.getElementById("carrera").value,
        sede_id: document.getElementById("sede").value,
        nivel: Number(document.getElementById("nivel").value),
    };
    const problema = problemaAntesDeGuardar(datos);
    if (problema) {
        document.getElementById(problema.campo).focus({ preventScroll: true });
        avisarEnPerfil("error", problema.mensaje);
        return;
    }

    const boton = document.getElementById("profileSave");
    boton.disabled = true;
    try {
        const r = await enviarPerfil(datos);
        if (r.ok) {
            mostrarPerfil(r.cuerpo);
            avisarEnPerfil("success", "Tu perfil quedó guardado.");
            document.dispatchEvent(new CustomEvent("perfil-guardado", { detail: r.cuerpo }));
        } else if (r.estado === 401) {
            mostrarSinSesion("Tu sesión terminó. Vuelve a iniciar sesión para guardar tu perfil.");
        } else {
            avisarEnPerfil("error", mensajeDeError(r.cuerpo, "No se pudo guardar el perfil."));
        }
    } catch {
        avisarEnPerfil("error", "No hay conexión con el servicio de Identidad.");
    } finally {
        boton.disabled = false;
    }
}
