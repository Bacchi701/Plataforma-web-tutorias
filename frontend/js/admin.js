// Panel de administracion (HU-33, parte 2; AD-09): las cuentas, las tutorias y
// sus evaluaciones, siempre con el token de acceso de la sesion:
//   GET    /api/identity/v1/admin/usuarios?buscar=&pagina=   -> las cuentas, por paginas (HU-31)
//   PATCH  /api/identity/v1/admin/usuarios/{id}              -> la activa o la desactiva (HU-31)
//   GET    /api/tutoring/v1/admin/reservas?estado=           -> las 100 reservas mas nuevas (HU-33, parte 1)
//   DELETE /api/tutoring/v1/admin/evaluaciones/{id}          -> retira una evaluacion (HU-33, parte 1)
// Sin la marca es_admin, la pagina no pide ninguna ruta /admin (criterio 1). La
// proteccion real es la de los servicios, que responden 403 no_es_administrador:
// la pagina solo evita mostrar lo que no sirve.
// Las fechas llegan en UTC y se muestran en hora de Chile (America/Santiago).
// Los datos se escriben con textContent, nunca con innerHTML: los nombres y los
// comentarios los escriben los usuarios.

// El encabezado (sesion.js) y esta pagina piden la sesion al mismo tiempo: la
// renovacion se comparte en Sesion.renovar (sesion.js).

// El resto va dentro de una funcion, para no chocar con los nombres globales
// de sesion.js (Sesion, IDENTIDAD, mensajeDeError, avisar...).
(() => {
    "use strict";

    const TUTORIAS = "/api/tutoring/v1";
    const ZONA_CHILE = "America/Santiago";
    const FORMATO_FECHA = {
        timeZone: ZONA_CHILE,
        weekday: "long",
        day: "numeric",
        month: "long",
        year: "numeric",
    };
    const FORMATO_DIA = {
        timeZone: ZONA_CHILE,
        day: "numeric",
        month: "long",
        year: "numeric",
    };
    const FORMATO_HORA = {
        timeZone: ZONA_CHILE,
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
    };
    // Los siete estados de una reserva, en palabras (anexo A, seccion 9).
    const ESTADOS = new Map([
        ["SOLICITADA", "Solicitada"],
        ["CONFIRMADA", "Confirmada"],
        ["RECHAZADA", "Rechazada"],
        ["EXPIRADA", "Expirada"],
        ["CANCELADA", "Cancelada"],
        ["REALIZADA", "Realizada"],
        ["EVALUADA", "Evaluada"],
    ]);
    const SIN_IDENTIDAD =
        "No hay conexión con el servicio de Identidad. Revisa que el sistema esté levantado.";
    const SIN_TUTORIAS =
        "No hay conexión con el servicio de Tutorías. Revisa que el sistema esté levantado.";
    const SESION_VENCIDA = "Tu sesión venció. Vuelve a iniciar sesión.";

    // El id del administrador de la sesion: su fila no tiene «Desactivar».
    let miId = null;
    // Lo que muestra la lista de cuentas: la busqueda y la pagina, ya cargadas.
    let busqueda = "";
    let pagina = 1;
    let totalPaginas = 1;
    // Cada carga lleva un numero: si dos se cruzan, solo se dibuja la ultima.
    let ultimaCargaUsuarios = 0;
    let ultimaCargaReservas = 0;
    // Despues de «sin sesion» o «sin acceso», el panel no vuelve a mostrarse.
    let panelCerrado = false;

    document.addEventListener("DOMContentLoaded", iniciar);

    function porId(id) {
        return document.getElementById(id);
    }

    // Criterio 1: primero la sesion y la marca, despues las rutas /admin.
    async function iniciar() {
        porId("formBuscar").addEventListener("submit", (evento) => {
            evento.preventDefault();
            cargarUsuarios(1, porId("buscar").value.trim());
        });
        porId("paginaAnterior").addEventListener("click", () => cargarUsuarios(pagina - 1));
        porId("paginaSiguiente").addEventListener("click", () => cargarUsuarios(pagina + 1));
        porId("filtroEstado").addEventListener("change", cargarReservas);

        let usuario = null;
        try {
            usuario = await Sesion.yo();
        } catch {
            porId("cargando").classList.add("hidden");
            mostrarAviso("error", SIN_IDENTIDAD);
            return;
        }
        if (!usuario) {
            porId("cargando").classList.add("hidden");
            mostrarSinSesion();
            return;
        }
        if (usuario.es_admin !== true) {
            porId("cargando").classList.add("hidden");
            mostrarSinAcceso();
            return;
        }
        miId = usuario.id;
        // Las dos secciones a la vez; si una falla, la otra igual se muestra.
        await Promise.all([cargarUsuarios(1, ""), cargarReservas()]);
        porId("cargando").classList.add("hidden");
        if (!panelCerrado) {
            porId("panel").classList.remove("hidden");
        }
    }

    // ------------------------------------------------------------ peticiones

    // A Identidad, con Sesion.pedir (sesion.js) y el token de acceso. Si vencio
    // (dura 30 minutos), se renueva una vez con la cookie y se reintenta.
    async function pedirIdentidad(ruta, opciones = {}) {
        const enviar = () =>
            Sesion.pedir(ruta, {
                ...opciones,
                headers: { Authorization: `Bearer ${Sesion.tokenAcceso}` },
            });
        let r = await enviar();
        if (r.estado === 401 && (await Sesion.renovar())) {
            r = await enviar();
        }
        return r;
    }

    // fetch a Tutorias con el token de acceso, con la misma renovacion, como en
    // disponibilidad.js.
    async function pedirTutorias(ruta, opciones = {}) {
        const enviar = () =>
            fetch(TUTORIAS + ruta, {
                ...opciones,
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${Sesion.tokenAcceso}`,
                },
            });
        let respuesta = await enviar();
        if (respuesta.status === 401 && (await Sesion.renovar())) {
            respuesta = await enviar();
        }
        let cuerpo = null;
        if (respuesta.status !== 204) {
            try {
                cuerpo = await respuesta.json();
            } catch {
                cuerpo = null;
            }
        }
        return { ok: respuesta.ok, estado: respuesta.status, cuerpo };
    }

    // Un 401 que no se pudo renovar: la sesion vencio. Un 403: la cuenta no es
    // administradora (no_es_administrador). En los dos, la pagina cambia de
    // estado y no sigue.
    function sinPermiso(r) {
        if (r.estado === 401) {
            mostrarSinSesion(SESION_VENCIDA);
            return true;
        }
        if (r.estado === 403) {
            mostrarSinAcceso();
            return true;
        }
        return false;
    }

    // ------------------------------------------------------------ usuarios (criterio 2)

    // Una pagina de cuentas, con la busqueda pedida. La busqueda y la pagina
    // quedan guardadas solo si la API las acepta.
    async function cargarUsuarios(numero, texto = busqueda) {
        const carga = ++ultimaCargaUsuarios;
        let ruta = "/admin/usuarios?";
        if (texto) {
            ruta += `buscar=${encodeURIComponent(texto)}&`;
        }
        ruta += `pagina=${numero}`;

        ponerBotonesDeUsuarios(true);
        let r;
        try {
            r = await pedirIdentidad(ruta);
        } catch {
            if (carga === ultimaCargaUsuarios) {
                mostrarAviso("error", SIN_IDENTIDAD);
                ponerBotonesDeUsuarios(false);
            }
            return;
        }
        if (carga !== ultimaCargaUsuarios) {
            return;
        }
        ponerBotonesDeUsuarios(false);
        if (sinPermiso(r)) {
            return;
        }
        if (!r.ok) {
            mostrarAviso("error", mensajeDeError(r.cuerpo, "No se pudieron cargar las cuentas."));
            return;
        }
        const datos = r.cuerpo;
        // La pagina pedida ya no existe (la lista cambio): se pide la ultima.
        if (datos.resultados.length === 0 && datos.pagina > datos.total_paginas) {
            await cargarUsuarios(datos.total_paginas, texto);
            return;
        }
        busqueda = texto;
        pagina = datos.pagina;
        totalPaginas = datos.total_paginas;
        dibujarUsuarios(datos);
    }

    // Mientras se carga una pagina, «Buscar», «Anterior» y «Siguiente» quedan
    // deshabilitados. Despues, «Anterior» y «Siguiente» segun la pagina.
    function ponerBotonesDeUsuarios(cargando) {
        porId("botonBuscar").disabled = cargando;
        porId("paginaAnterior").disabled = cargando || pagina <= 1;
        porId("paginaSiguiente").disabled = cargando || pagina >= totalPaginas;
    }

    function dibujarUsuarios(datos) {
        porId("listaUsuarios").replaceChildren(...datos.resultados.map(filaDeUsuario));
        porId("totalUsuarios").textContent = cantidad(datos.total, "cuenta", "cuentas");
        porId("textoPagina").textContent = `Página ${datos.pagina} de ${datos.total_paginas}`;
        ponerBotonesDeUsuarios(false);
        const vacio = porId("sinUsuarios");
        vacio.textContent = busqueda
            ? `Ninguna cuenta coincide con «${busqueda}».`
            : "Todavía no hay cuentas.";
        vacio.classList.toggle("hidden", datos.resultados.length > 0);
    }

    // Una cuenta: nombre y apellido, el correo (solo en este panel, RNF-07) y
    // sus marcas. La del administrador de la sesion no tiene boton: HU-31
    // igual responde 409 cuenta_propia.
    function filaDeUsuario(cuenta) {
        const item = elemento("li", cuenta.activo ? "adm-usuario" : "adm-usuario adm-usuario-desactivada");
        const datos = elemento("div", "adm-usuario-datos");
        datos.appendChild(elemento("strong", "adm-usuario-nombre", nombreCompleto(cuenta)));
        if (cuenta.email) {
            datos.appendChild(elemento("span", "adm-usuario-correo", cuenta.email));
        }
        const marcas = elemento("div", "adm-marcas");
        marcas.appendChild(
            cuenta.activo
                ? elemento("span", "adm-marca adm-marca-activa", "Activa")
                : elemento("span", "adm-marca adm-marca-desactivada", "Desactivada")
        );
        if (cuenta.email_verificado === false) {
            marcas.appendChild(elemento("span", "adm-marca adm-marca-sin-verificar", "Sin verificar"));
        }
        if (cuenta.es_admin === true) {
            marcas.appendChild(elemento("span", "adm-marca adm-marca-admin", "Administrador"));
        }
        if (cuenta.id === miId) {
            marcas.appendChild(elemento("span", "adm-marca adm-marca-propia", "Tu cuenta"));
        }
        datos.appendChild(marcas);
        item.appendChild(datos);
        if (cuenta.id !== miId) {
            item.appendChild(botonDeEstado(cuenta));
        }
        return item;
    }

    function botonDeEstado(cuenta) {
        const desactivar = cuenta.activo === true;
        const nombre = nombreCompleto(cuenta);
        const nodo = desactivar
            ? boton("Desactivar", "fa-solid fa-user-slash", "adm-boton adm-boton-peligro", `Desactivar la cuenta de ${nombre}`)
            : boton("Activar", "fa-solid fa-user-check", "adm-boton", `Activar la cuenta de ${nombre}`);
        nodo.addEventListener("click", () => cambiarEstado(cuenta, !desactivar, nodo));
        return nodo;
    }

    // PATCH con {"activo": false} o {"activo": true}, despues de confirmar.
    async function cambiarEstado(cuenta, activo, nodo) {
        const nombre = nombreCompleto(cuenta);
        const pregunta = activo
            ? `¿Activar la cuenta de ${nombre}? Podrá volver a iniciar sesión.`
            : `¿Desactivar la cuenta de ${nombre}? No podrá iniciar sesión y se cerrarán sus sesiones abiertas.`;
        if (!window.confirm(pregunta)) {
            return;
        }
        nodo.disabled = true;
        let r;
        try {
            r = await pedirIdentidad(`/admin/usuarios/${encodeURIComponent(cuenta.id)}`, {
                method: "PATCH",
                body: JSON.stringify({ activo }),
            });
        } catch {
            mostrarAviso("error", SIN_IDENTIDAD);
            nodo.disabled = false;
            return;
        }
        if (sinPermiso(r)) {
            return;
        }
        if (!r.ok) {
            // 400, 404 o 409 (cuenta_propia): el mensaje de la API.
            mostrarAviso("error", mensajeDeError(r.cuerpo, "No se pudo cambiar el estado de la cuenta."));
            nodo.disabled = false;
            return;
        }
        mostrarAviso(
            "exito",
            activo
                ? `La cuenta de ${nombre} quedó activa: puede volver a iniciar sesión.`
                : textoDeDesactivada(nombre, Number(r.cuerpo?.sesiones_revocadas) || 0)
        );
        await cargarUsuarios(pagina);
    }

    // CA7: ya no puede iniciar sesion, y sus renovaciones quedaron revocadas.
    // La busqueda de tutores la deja fuera en la siguiente sincronizacion de
    // las copias de Tutorias (HU-19), que el programador corre cada 5 minutos.
    function textoDeDesactivada(nombre, sesiones) {
        let cerradas = "";
        if (sesiones === 1) {
            cerradas = " (se cerró 1 sesión abierta)";
        } else if (sesiones > 1) {
            cerradas = ` (se cerraron ${sesiones} sesiones abiertas)`;
        }
        return (
            `La cuenta de ${nombre} quedó desactivada: ya no puede iniciar sesión${cerradas}. ` +
            "Deja de aparecer en la búsqueda de tutores en la próxima sincronización (hasta 5 minutos)."
        );
    }

    // ------------------------------------------------------------ tutorias (criterios 3 y 4)

    async function cargarReservas() {
        const carga = ++ultimaCargaReservas;
        const estado = porId("filtroEstado").value;
        const ruta = estado ? `/admin/reservas?estado=${encodeURIComponent(estado)}` : "/admin/reservas";
        let r;
        try {
            r = await pedirTutorias(ruta);
        } catch {
            if (carga === ultimaCargaReservas) {
                mostrarAviso("error", SIN_TUTORIAS);
            }
            return;
        }
        if (carga !== ultimaCargaReservas || sinPermiso(r)) {
            return;
        }
        if (!r.ok) {
            mostrarAviso("error", mensajeDeError(r.cuerpo, "No se pudieron cargar las tutorías."));
            return;
        }
        dibujarReservas(Array.isArray(r.cuerpo) ? r.cuerpo : [], estado);
    }

    function dibujarReservas(reservas, estado) {
        porId("listaReservas").replaceChildren(...reservas.map(tarjetaDeReserva));
        const vacio = porId("sinReservas");
        vacio.textContent = estado
            ? `No hay tutorías en estado «${ESTADOS.get(estado) || estado}».`
            : "Todavía no hay tutorías.";
        vacio.classList.toggle("hidden", reservas.length > 0);
    }

    // Criterio 3: la asignatura, el tutor y quien la solicito, la fecha y la
    // hora de Chile del bloque, el estado y cuando se solicito.
    function tarjetaDeReserva(reserva) {
        const clase = String(reserva.estado).toLowerCase();
        const item = elemento("li", `adm-reserva adm-reserva-${clase}`);

        const asignatura = elemento("div", "adm-asignatura");
        asignatura.append(
            elemento("span", "adm-sigla", reserva.asignatura.sigla),
            elemento("strong", "adm-asignatura-nombre", reserva.asignatura.nombre)
        );
        const cabecera = elemento("div", "adm-reserva-cabecera");
        cabecera.append(
            asignatura,
            elemento("span", `adm-estado adm-estado-${clase}`, ESTADOS.get(reserva.estado) || reserva.estado)
        );

        item.append(
            cabecera,
            persona("Tutor: ", reserva.tutor),
            persona("Estudiante: ", reserva.solicitante),
            elemento("p", "adm-cuando", describir(reserva.bloque)),
            elemento(
                "p",
                "adm-solicitada",
                `Solicitada el ${diaDeChile(reserva.creada_en)} a las ${horaDeChile(reserva.creada_en)}`
            )
        );
        if (reserva.evaluacion) {
            item.appendChild(evaluacion(reserva));
        }
        return item;
    }

    function persona(etiqueta, quien) {
        const nodo = elemento("p", "adm-persona");
        nodo.append(elemento("span", "adm-etiqueta", etiqueta), nombreCompleto(quien));
        return nodo;
    }

    // Criterio 4: la nota con estrellas, el comentario y, si ya esta retirada,
    // cuando; si no, «Retirar evaluacion».
    function evaluacion(reserva) {
        const ev = reserva.evaluacion;
        const caja = elemento("div", ev.retirada_en ? "adm-evaluacion adm-evaluacion-retirada" : "adm-evaluacion");
        const cabecera = elemento("div", "adm-evaluacion-cabecera");
        cabecera.append(elemento("span", "adm-etiqueta", "Evaluación"), estrellas(ev.calificacion));
        caja.append(
            cabecera,
            ev.comentario
                ? elemento("p", "adm-comentario", ev.comentario)
                : elemento("p", "adm-comentario adm-sin-comentario", "Sin comentario.")
        );
        if (ev.retirada_en) {
            caja.appendChild(elemento("p", "adm-retirada", `Retirada el ${diaDeChile(ev.retirada_en)}`));
            return caja;
        }
        const tutor = nombreCompleto(reserva.tutor);
        const nodo = boton(
            "Retirar evaluación",
            "fa-solid fa-eye-slash",
            "adm-boton adm-boton-peligro",
            `Retirar evaluación de ${nombreCompleto(reserva.solicitante)} a ${tutor} en ${reserva.asignatura.nombre}`
        );
        nodo.addEventListener("click", () => retirar(ev, tutor, nodo));
        caja.appendChild(nodo);
        return caja;
    }

    // Las estrellas de una calificacion, como evaluacionVisible de tutor.js.
    function estrellas(calificacion) {
        const nodo = elemento("span", "adm-estrellas");
        nodo.setAttribute("role", "img");
        nodo.setAttribute("aria-label", `Calificación ${calificacion} de 5`);
        for (let numero = 1; numero <= 5; numero++) {
            const estrella = elemento("i", numero <= calificacion ? "fa-solid fa-star" : "fa-regular fa-star");
            estrella.setAttribute("aria-hidden", "true");
            nodo.appendChild(estrella);
        }
        return nodo;
    }

    // DELETE, despues de confirmar. Con 204, el aviso y la lista de nuevo. Con
    // un 404 o un 409 (evaluacion_ya_retirada), la evaluacion cambio desde que
    // se cargo la lista: el mensaje de la API y la lista de nuevo.
    async function retirar(ev, tutor, nodo) {
        if (!window.confirm(`¿Retirar esta evaluación? Deja de contar para la reputación de ${tutor}.`)) {
            return;
        }
        nodo.disabled = true;
        let r;
        try {
            r = await pedirTutorias(`/admin/evaluaciones/${encodeURIComponent(ev.id)}`, { method: "DELETE" });
        } catch {
            mostrarAviso("error", SIN_TUTORIAS);
            nodo.disabled = false;
            return;
        }
        if (sinPermiso(r)) {
            return;
        }
        if (r.ok) {
            mostrarAviso("exito", `Evaluación retirada: ya no cuenta para la reputación de ${tutor}.`);
            await cargarReservas();
            return;
        }
        mostrarAviso("error", mensajeDeError(r.cuerpo, "No se pudo retirar la evaluación."));
        if (r.estado === 404 || r.estado === 409) {
            await cargarReservas();
            return;
        }
        nodo.disabled = false;
    }

    // ------------------------------------------------------------ avisos y estados

    // Como mostrarAviso de disponibilidad.js. No usa avisar() de sesion.js,
    // que pone la clase login-message, con estilos solo en perfil.css.
    function mostrarAviso(tipo, texto) {
        const caja = porId("aviso");
        caja.className = `adm-aviso adm-aviso-${tipo}`;
        caja.textContent = texto;
        caja.scrollIntoView({ block: "nearest" });
    }

    function ocultarAviso() {
        const caja = porId("aviso");
        caja.className = "adm-aviso hidden";
        caja.textContent = "";
    }

    function mostrarSinSesion(texto) {
        panelCerrado = true;
        porId("panel").classList.add("hidden");
        porId("sinAcceso").classList.add("hidden");
        porId("sinSesion").classList.remove("hidden");
        if (texto) {
            porId("sinSesionTexto").textContent = texto;
        }
        ocultarAviso();
    }

    function mostrarSinAcceso() {
        panelCerrado = true;
        porId("panel").classList.add("hidden");
        porId("sinSesion").classList.add("hidden");
        porId("sinAcceso").classList.remove("hidden");
        ocultarAviso();
    }

    // ------------------------------------------------------------ ayudas

    function elemento(etiqueta, clase, texto) {
        const nodo = document.createElement(etiqueta);
        if (clase) nodo.className = clase;
        if (texto !== undefined) nodo.textContent = texto;
        return nodo;
    }

    // Un boton con icono. El nombre accesible empieza con el texto del boton
    // (asi lo encuentra quien lo nombra por voz) y dice a quien afecta.
    function boton(texto, icono, clase, etiqueta) {
        const nodo = elemento("button", clase);
        nodo.type = "button";
        nodo.setAttribute("aria-label", etiqueta);
        const simbolo = elemento("i", icono);
        simbolo.setAttribute("aria-hidden", "true");
        nodo.append(simbolo, elemento("span", null, texto));
        return nodo;
    }

    function nombreCompleto(persona) {
        return `${persona.nombre} ${persona.apellido}`;
    }

    function cantidad(numero, singular, plural) {
        return `${numero} ${numero === 1 ? singular : plural}`;
    }

    function fechaDeChile(iso) {
        return new Date(iso).toLocaleString("es-CL", FORMATO_FECHA);
    }

    // "25 de septiembre de 2026"
    function diaDeChile(iso) {
        return new Date(iso).toLocaleString("es-CL", FORMATO_DIA);
    }

    function horaDeChile(iso) {
        return new Date(iso).toLocaleString("es-CL", FORMATO_HORA);
    }

    // "lunes, 21 de septiembre de 2026, de 18:00 a 19:00", como en
    // disponibilidad.js, y la fecha del termino si es otro dia.
    function describir(bloque) {
        const inicio = bloque.inicio_en;
        const fin = bloque.fin_en;
        const texto = `${fechaDeChile(inicio)}, de ${horaDeChile(inicio)} a ${horaDeChile(fin)}`;
        const otroDia = fechaDeChile(fin) !== fechaDeChile(inicio);
        return otroDia ? `${texto} (termina el ${fechaDeChile(fin)})` : texto;
    }
})();
