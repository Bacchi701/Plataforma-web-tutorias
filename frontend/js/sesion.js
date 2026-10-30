// Sesion en el navegador (Pilar 2, seccion 5.5).
// - El token de acceso vive solo en memoria: al recargar la pagina se pierde.
// - La renovacion viaja en una cookie httpOnly que el navegador envia solo a
//   /api/identity/v1/ y que este codigo nunca puede leer.
// Por eso, al abrir cualquier pagina, lo primero es pedir /refresh.

const IDENTIDAD = "/api/identity/v1";

const Sesion = {
    tokenAcceso: null,

    async pedir(ruta, opciones = {}) {
        const respuesta = await fetch(IDENTIDAD + ruta, {
            credentials: "same-origin",
            ...opciones,
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
                ...(opciones.headers || {}),
            },
        });
        let cuerpo = null;
        if (respuesta.status !== 204) {
            try {
                cuerpo = await respuesta.json();
            } catch {
                cuerpo = null;
            }
        }
        return { ok: respuesta.ok, estado: respuesta.status, cuerpo };
    },

    async entrar(email, password) {
        const r = await this.pedir("/login", {
            method: "POST",
            body: JSON.stringify({ email, password }),
        });
        this.tokenAcceso = r.ok ? r.cuerpo.token_acceso : null;
        return r;
    },

    async renovar() {
        const r = await this.pedir("/refresh", { method: "POST" });
        this.tokenAcceso = r.ok ? r.cuerpo.token_acceso : null;
        return r.ok;
    },

    async yo() {
        if (!this.tokenAcceso && !(await this.renovar())) {
            return null;
        }
        const r = await this.pedir("/yo", {
            headers: { Authorization: `Bearer ${this.tokenAcceso}` },
        });
        return r.ok ? r.cuerpo : null;
    },

    async salir() {
        await this.pedir("/logout", { method: "POST" });
        this.tokenAcceso = null;
    },
};

// Texto para el usuario a partir del formato de error de la API:
// { codigo, mensaje, detalles }. Los detalles por campo van primero.
function mensajeDeError(cuerpo, porDefecto) {
    if (!cuerpo) {
        return porDefecto;
    }
    if (cuerpo.detalles && typeof cuerpo.detalles === "object") {
        const textos = Object.values(cuerpo.detalles).flat().filter(Boolean);
        if (textos.length) {
            return textos.join(" ");
        }
    }
    return cuerpo.mensaje || porDefecto;
}

// Muestra un aviso en las cajas .login-message o .register-message.
function avisar(caja, tipo, texto) {
    const base = caja.classList.contains("register-message")
        ? "register-message"
        : "login-message";
    caja.className = `${base} ${tipo}`;
    caja.textContent = texto;
}

// Con sesion abierta, el encabezado cambia "Iniciar sesion / Registrarme"
// por el nombre y el boton para salir (HU-09, criterio 4).
async function mostrarSesionEnEncabezado() {
    const acciones = document.querySelector(".nav-actions");
    if (!acciones) {
        return;
    }
    let usuario = null;
    try {
        usuario = await Sesion.yo();
    } catch {
        return; // sin conexion con Identidad: el encabezado queda como esta
    }
    if (!usuario) {
        return;
    }

    // Paginas de la cuenta, antes del saludo (HU-10). Disponibilidad es de HU-15.
    const perfil = document.createElement("a");
    perfil.href = "perfil.html";
    perfil.className = "btn-login";
    perfil.textContent = "Mi perfil";

    const disponibilidad = document.createElement("a");
    disponibilidad.href = "disponibilidad.html";
    disponibilidad.className = "btn-login";
    disponibilidad.textContent = "Mi disponibilidad";

    const saludo = document.createElement("span");
    saludo.className = "btn-login";
    saludo.textContent = `Hola, ${usuario.nombre}`;

    const salir = document.createElement("button");
    salir.type = "button";
    salir.className = "btn-primary";
    salir.style.border = "none";
    salir.style.cursor = "pointer";
    salir.textContent = "Cerrar sesión";
    salir.addEventListener("click", async () => {
        await Sesion.salir();
        window.location.href = "index.html";
    });

    acciones.replaceChildren(perfil, disponibilidad, saludo, salir);
}

document.addEventListener("DOMContentLoaded", mostrarSesionEnEncabezado);

// Boton ☰ del encabezado: hasta 950 px, .nav-menu y .nav-actions se esconden
// y este boton los muestra debajo de la marca (.menu-abierto en styles.css).
// Se cierra con Escape o al elegir un enlace.
function activarMenuMovil() {
    const boton = document.querySelector(".mobile-menu");
    const encabezado = document.querySelector(".header");
    if (!boton || !encabezado) {
        return;
    }
    boton.type = "button";
    boton.setAttribute("aria-label", "Abrir menú");
    boton.setAttribute("aria-expanded", "false");

    const marcar = (abierto) => {
        encabezado.classList.toggle("menu-abierto", abierto);
        boton.setAttribute("aria-expanded", String(abierto));
        boton.setAttribute("aria-label", abierto ? "Cerrar menú" : "Abrir menú");
    };

    boton.addEventListener("click", () => {
        marcar(!encabezado.classList.contains("menu-abierto"));
    });

    document.addEventListener("keydown", (evento) => {
        if (evento.key !== "Escape" || !encabezado.classList.contains("menu-abierto")) {
            return;
        }
        // Si el foco estaba en el menu, vuelve al boton en vez de perderse.
        const focoEnMenu = encabezado.contains(document.activeElement);
        marcar(false);
        if (focoEnMenu) {
            boton.focus();
        }
    });

    // En el encabezado y no en cada enlace: .nav-actions cambia sus enlaces
    // al abrir la sesion (mostrarSesionEnEncabezado).
    encabezado.addEventListener("click", (evento) => {
        if (evento.target.closest(".nav-menu a, .nav-actions a")) {
            marcar(false);
        }
    });
}

document.addEventListener("DOMContentLoaded", activarMenuMovil);
