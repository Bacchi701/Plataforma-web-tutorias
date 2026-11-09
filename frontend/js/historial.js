// Pagina "Mi historial" (HU-26): las tutorias que ya terminaron, las que el
// usuario pidio y las que dio, y desde ahi la evaluacion al tutor (HU-25),
// siempre con su token de acceso:
//   GET  /api/tutoring/v1/reservas?rol=estudiante   -> las que solicito (HU-21)
//   GET  /api/tutoring/v1/reservas?rol=tutor        -> las de sus bloques (HU-21)
//   POST /api/tutoring/v1/reservas/{id}/evaluacion  -> evalua una REALIZADA (HU-25)
// Muestra solo lo terminado: REALIZADA, EVALUADA, CANCELADA, RECHAZADA y
// EXPIRADA. Lo vigente (SOLICITADA y CONFIRMADA) es de la pantalla «Mis
// reservas y solicitudes recibidas» (HU-30).
// Las fechas llegan en UTC y se muestran en hora de Chile (America/Santiago).
// Los datos se escriben con textContent, nunca con innerHTML.

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
    const FORMATO_HORA = {
        timeZone: ZONA_CHILE,
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
    };
    // Lo terminado, en palabras. Lo que no esta aqui (lo vigente) no se muestra.
    const ESTADOS = new Map([
        ["REALIZADA", "Realizada"],
        ["EVALUADA", "Evaluada"],
        ["CANCELADA", "Cancelada"],
        ["RECHAZADA", "Rechazada"],
        ["EXPIRADA", "Expirada"],
    ]);
    const SECCIONES = {
        estudiante: { lista: "listaEstudiante", vacio: "vacioEstudiante" },
        tutor: { lista: "listaTutor", vacio: "vacioTutor" },
    };
    // El comentario de una evaluacion: hasta 500 caracteres (HU-25).
    const LARGO_COMENTARIO = 500;
    const NOTA_VACIA = "Escribe una nota de 1 a 5.";
    const NOTA_NO_ENTERA = "La nota tiene que ser un número entero de 1 a 5.";
    const SIN_CONEXION =
        "No hay conexión con el servicio de Tutorías. Revisa que el sistema esté levantado.";

    document.addEventListener("DOMContentLoaded", iniciar);

    function porId(id) {
        return document.getElementById(id);
    }

    async function iniciar() {
        let usuario = null;
        try {
            usuario = await Sesion.yo();
        } catch {
            porId("cargando").classList.add("hidden");
            mostrarAviso("error", "No hay conexión con el servicio de Identidad.");
            return;
        }
        if (!usuario) {
            porId("cargando").classList.add("hidden");
            mostrarSinSesion();
            return;
        }
        await cargarHistorial();
        porId("cargando").classList.add("hidden");
    }

    // fetch a Tutorias con el token de acceso. Si vencio (dura 30 minutos), se
    // renueva una vez con la cookie y se reintenta, como en disponibilidad.js.
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

    // Las dos listas, en paralelo (criterio 1). Si una falla, no se dibuja
    // ninguna: el historial no queda a medias sin que se note.
    async function cargarHistorial() {
        let respuestas;
        try {
            respuestas = await Promise.all([
                pedirTutorias("/reservas?rol=estudiante"),
                pedirTutorias("/reservas?rol=tutor"),
            ]);
        } catch {
            mostrarAviso("error", SIN_CONEXION);
            return;
        }
        if (respuestas.some((r) => r.estado === 401)) {
            mostrarSinSesion("Tu sesión venció. Vuelve a iniciar sesión para ver tu historial.");
            return;
        }
        const fallida = respuestas.find((r) => !r.ok);
        if (fallida) {
            mostrarAviso("error", mensajeDeError(fallida.cuerpo, "No se pudo cargar tu historial."));
            return;
        }
        dibujarSeccion("estudiante", terminadas(respuestas[0].cuerpo));
        dibujarSeccion("tutor", terminadas(respuestas[1].cuerpo));
        porId("conSesion").classList.remove("hidden");
    }

    // Solo lo terminado, del bloque mas reciente al mas antiguo. La API las
    // manda por creada_en: con el mismo inicio quedan en ese orden, porque sort
    // no cambia el orden de los empates.
    function terminadas(cuerpo) {
        const reservas = Array.isArray(cuerpo) ? cuerpo : [];
        return reservas
            .filter((reserva) => ESTADOS.has(reserva.estado))
            .sort((a, b) => Date.parse(b.bloque.inicio_en) - Date.parse(a.bloque.inicio_en));
    }

    // ------------------------------------------------------------ dibujo

    function dibujarSeccion(rol, reservas) {
        const { lista, vacio } = SECCIONES[rol];
        porId(lista).replaceChildren(...reservas.map((reserva) => tarjeta(reserva, rol)));
        porId(vacio).classList.toggle("hidden", reservas.length > 0);
    }

    // Criterio 1: la asignatura, con quien, la fecha y la hora de Chile, y el estado.
    function tarjeta(reserva, rol) {
        const clase = reserva.estado.toLowerCase();
        const item = elemento("li", `hist-item hist-item-${clase}`);

        const asignatura = elemento("div", "hist-asignatura");
        asignatura.append(
            elemento("span", "hist-sigla", reserva.asignatura.sigla),
            elemento("strong", "hist-asignatura-nombre", reserva.asignatura.nombre)
        );
        const cabecera = elemento("div", "hist-item-cabecera");
        cabecera.append(
            asignatura,
            elemento("span", `hist-estado hist-estado-${clase}`, ESTADOS.get(reserva.estado))
        );

        // En «Como estudiante», el tutor; en «Como tutor», quien la solicito.
        const comoEstudiante = rol === "estudiante";
        const persona = elemento("p", "hist-persona");
        persona.append(
            elemento("span", "hist-persona-rol", comoEstudiante ? "Tutor: " : "Estudiante: "),
            nombreCompleto(comoEstudiante ? reserva.tutor : reserva.solicitante)
        );

        item.append(cabecera, persona, elemento("p", "hist-cuando", describir(reserva.bloque)));
        if (sePuedeEvaluar(reserva, rol)) {
            item.appendChild(evaluacion(reserva));
        }
        // HU-24: el pago de una tutoria con monto, tambien de una que ya paso.
        if (Number(reserva.monto) > 0) {
            item.appendChild(enlaceAlPago(reserva));
        }
        return item;
    }

    // Criterio 2: solo quien la solicito, y solo si esta REALIZADA. Una
    // EVALUADA, o una de «Como tutor», no tiene ninguna opcion de evaluar.
    function sePuedeEvaluar(reserva, rol) {
        return rol === "estudiante" && reserva.rol === "estudiante" && reserva.estado === "REALIZADA";
    }

    // El boton «Evaluar» y el formulario que abre dentro de la misma tarjeta.
    function evaluacion(reserva) {
        const id = reserva.id;
        const tutoria = `${reserva.asignatura.nombre} con ${nombreCompleto(reserva.tutor)}`;

        const abrir = boton("Evaluar", "fa-solid fa-star", "hist-boton", `Evaluar la tutoría de ${tutoria}`);

        // novalidate: la validacion la hace la pagina, con sus mensajes (criterio 3).
        const formulario = elemento("form", "hist-formulario hidden");
        formulario.noValidate = true;
        formulario.setAttribute("aria-label", `Evaluación de la tutoría de ${tutoria}`);

        // Un campo que se escribe, no una lista: asi se puede escribir una
        // nota fuera de rango y ver el mensaje.
        const nota = document.createElement("input");
        nota.type = "number";
        nota.id = `hist-nota-${id}`;
        nota.min = "1";
        nota.max = "5";
        nota.step = "1";
        nota.setAttribute("inputmode", "numeric");
        const errorNota = mensajeDeCampo(`hist-error-nota-${id}`);
        nota.setAttribute("aria-describedby", errorNota.id);

        // Sin maxlength: el contador avisa y la validacion de abajo lo detiene.
        const comentario = document.createElement("textarea");
        comentario.id = `hist-comentario-${id}`;
        comentario.rows = 3;
        const contador = elemento("small", "hist-contador");
        contador.id = `hist-contador-${id}`;
        const errorComentario = mensajeDeCampo(`hist-error-comentario-${id}`);
        comentario.setAttribute("aria-describedby", `${contador.id} ${errorComentario.id}`);

        // Lo que la API rechaza sin ser de un campo (por ejemplo, un 409).
        const errorEnvio = mensajeDeCampo(`hist-error-envio-${id}`);
        errorEnvio.setAttribute("role", "alert");

        const enviar = elemento("button", "btn-primary", "Enviar evaluación");
        enviar.type = "submit";
        const cancelar = elemento("button", "hist-boton", "Cancelar");
        cancelar.type = "button";
        const acciones = elemento("div", "hist-form-acciones");
        acciones.append(enviar, cancelar);

        formulario.append(
            campo("Tu nota, de 1 a 5", nota, errorNota),
            campo("Comentario (opcional)", comentario, contador, errorComentario),
            errorEnvio,
            acciones
        );

        // «N/500», en rojo sobre 500, contado como lo cuenta el servidor.
        const contar = () => {
            const largo = largoDelComentario(comentario.value);
            contador.textContent = `${largo}/${LARGO_COMENTARIO}`;
            contador.classList.toggle("hist-contador-excedido", largo > LARGO_COMENTARIO);
        };
        contar();
        comentario.addEventListener("input", () => {
            contar();
            ocultarMensaje(errorComentario, comentario);
        });
        nota.addEventListener("input", () => ocultarMensaje(errorNota, nota));

        abrir.addEventListener("click", () => {
            abrir.classList.add("hidden");
            formulario.classList.remove("hidden");
            nota.focus();
        });
        cancelar.addEventListener("click", () => {
            formulario.reset();
            contar();
            ocultarMensaje(errorNota, nota);
            ocultarMensaje(errorComentario, comentario);
            ocultarMensaje(errorEnvio);
            formulario.classList.add("hidden");
            abrir.classList.remove("hidden");
            abrir.focus();
        });

        formulario.addEventListener("submit", async (evento) => {
            evento.preventDefault();
            if (enviar.disabled) {
                return;
            }
            ocultarMensaje(errorEnvio);

            // Criterio 3: todo se revisa antes de enviar. Si hay algo que
            // corregir, no sale ninguna peticion.
            const problemaNota = problemaDeLaNota(nota);
            const largo = largoDelComentario(comentario.value);
            const problemaComentario =
                largo > LARGO_COMENTARIO
                    ? `El comentario tiene ${largo} caracteres: puede tener hasta ${LARGO_COMENTARIO}.`
                    : null;
            mostrarUOcultar(errorNota, nota, problemaNota);
            mostrarUOcultar(errorComentario, comentario, problemaComentario);
            if (problemaNota || problemaComentario) {
                (problemaNota ? nota : comentario).focus();
                return;
            }

            // La nota va como numero: la API rechaza "4" entre comillas.
            const cuerpo = JSON.stringify({
                calificacion: Number(nota.value),
                comentario: comentario.value.trim() || null,
            });
            const campos = { nota, errorNota, comentario, errorComentario, errorEnvio };
            enviar.disabled = true;
            try {
                await enviarEvaluacion(id, cuerpo, campos);
            } finally {
                enviar.disabled = false;
            }
        });

        const contenedor = elemento("div", "hist-evaluar");
        contenedor.append(abrir, formulario);
        return contenedor;
    }

    // POST de la evaluacion. Con 201, el aviso y el historial de nuevo: la
    // tutoria queda Evaluada y sin el boton (criterio 2).
    async function enviarEvaluacion(id, cuerpo, campos) {
        let r;
        try {
            r = await pedirTutorias(`/reservas/${encodeURIComponent(id)}/evaluacion`, {
                method: "POST",
                body: cuerpo,
            });
        } catch {
            mostrarMensaje(campos.errorEnvio, null, SIN_CONEXION);
            return;
        }
        if (r.ok) {
            mostrarAviso("exito", "¡Gracias! Tu evaluación quedó guardada.");
            await cargarHistorial();
            return;
        }
        if (r.estado === 401) {
            mostrarSinSesion("Tu sesión venció. Vuelve a iniciar sesión para evaluar la tutoría.");
            return;
        }
        const texto = mensajeDeError(r.cuerpo, "No se pudo guardar la evaluación.");
        const codigo = r.cuerpo?.codigo;
        if (codigo === "reserva_ya_evaluada") {
            mostrarAviso("error", texto);
            await cargarHistorial();
        } else if (codigo === "calificacion_invalida") {
            mostrarMensaje(campos.errorNota, campos.nota, texto);
            campos.nota.focus();
        } else if (codigo === "comentario_invalido") {
            mostrarMensaje(campos.errorComentario, campos.comentario, texto);
            campos.comentario.focus();
        } else {
            mostrarMensaje(campos.errorEnvio, null, texto);
        }
    }

    // ------------------------------------------------------------ validacion

    // Un input number da "" vacio y tambien con algo que no es un numero (por
    // ejemplo, "4,5" en algunos navegadores): validity.badInput los distingue.
    function problemaDeLaNota(campo) {
        if (campo.value === "") {
            return campo.validity.badInput ? NOTA_NO_ENTERA : NOTA_VACIA;
        }
        const valor = Number(campo.value);
        return Number.isInteger(valor) && valor >= 1 && valor <= 5 ? null : NOTA_NO_ENTERA;
    }

    // Como el servidor: sin los espacios de los lados y por caracteres, no por
    // unidades de UTF-16 (un emoji cuenta como uno).
    function largoDelComentario(texto) {
        return Array.from(texto.trim()).length;
    }

    // ------------------------------------------------------------ avisos

    function mostrarAviso(tipo, texto) {
        const caja = porId("aviso");
        caja.className = `hist-aviso hist-aviso-${tipo}`;
        caja.textContent = texto;
        caja.scrollIntoView({ block: "nearest" });
    }

    function ocultarAviso() {
        const caja = porId("aviso");
        caja.className = "hist-aviso hidden";
        caja.textContent = "";
    }

    function mostrarSinSesion(texto) {
        porId("conSesion").classList.add("hidden");
        porId("sinSesion").classList.remove("hidden");
        const parrafo = porId("sinSesionTexto");
        parrafo.textContent = texto || "";
        parrafo.classList.toggle("hidden", !texto);
        ocultarAviso();
    }

    // El mensaje junto al campo que hay que corregir.
    function mostrarMensaje(caja, control, texto) {
        caja.textContent = texto;
        caja.classList.remove("hidden");
        if (control) {
            control.setAttribute("aria-invalid", "true");
        }
    }

    function ocultarMensaje(caja, control) {
        caja.textContent = "";
        caja.classList.add("hidden");
        if (control) {
            control.removeAttribute("aria-invalid");
        }
    }

    function mostrarUOcultar(caja, control, texto) {
        if (texto) {
            mostrarMensaje(caja, control, texto);
        } else {
            ocultarMensaje(caja, control);
        }
    }

    // ------------------------------------------------------------ ayudas

    function elemento(etiqueta, clase, texto) {
        const nodo = document.createElement(etiqueta);
        if (clase) nodo.className = clase;
        if (texto !== undefined) nodo.textContent = texto;
        return nodo;
    }

    function boton(texto, icono, clase, etiqueta) {
        const nodo = elemento("button", clase);
        nodo.type = "button";
        nodo.setAttribute("aria-label", etiqueta);
        const simbolo = elemento("i", icono);
        simbolo.setAttribute("aria-hidden", "true");
        nodo.append(simbolo, ` ${texto}`);
        return nodo;
    }

    // La etiqueta arriba y, debajo del campo, el contador y el mensaje.
    function campo(texto, control, ...debajo) {
        const caja = elemento("div", "hist-campo");
        const etiqueta = elemento("label", null, texto);
        etiqueta.htmlFor = control.id;
        caja.append(etiqueta, control, ...debajo);
        return caja;
    }

    function mensajeDeCampo(id) {
        const nodo = elemento("p", "hist-error hidden");
        nodo.id = id;
        return nodo;
    }

    function nombreCompleto(persona) {
        return `${persona.nombre} ${persona.apellido}`;
    }

    function fechaDeChile(iso) {
        return new Date(iso).toLocaleString("es-CL", FORMATO_FECHA);
    }

    function horaDeChile(iso) {
        return new Date(iso).toLocaleString("es-CL", FORMATO_HORA);
    }

    // "jueves, 24 de septiembre de 2026, de 15:00 a 16:30", como en
    // disponibilidad.js, y la fecha del termino si es otro dia.
    function describir(bloque) {
        const inicio = bloque.inicio_en;
        const fin = bloque.fin_en;
        const texto = `${fechaDeChile(inicio)}, de ${horaDeChile(inicio)} a ${horaDeChile(fin)}`;
        const otroDia = fechaDeChile(fin) !== fechaDeChile(inicio);
        return otroDia ? `${texto} (termina el ${fechaDeChile(fin)})` : texto;
    }

    // ------------------------------------------------------------ el pago (HU-24)

    // «Ver pago»: el detalle de la tutoria y su pago simulado, en pago.html.
    // Por aqui se paga una tutoria que ya paso, porque «Mis reservas» (HU-30)
    // muestra solo lo vigente.
    function enlaceAlPago(reserva) {
        const enlace = elemento("a", "hist-boton hist-ver-pago");
        enlace.href = `pago.html?reserva=${encodeURIComponent(reserva.id)}`;
        enlace.setAttribute(
            "aria-label",
            `Ver pago de la tutoría de ${reserva.asignatura.nombre}, ${describir(reserva.bloque)}`
        );
        const icono = elemento("i", "fa-solid fa-receipt");
        icono.setAttribute("aria-hidden", "true");
        enlace.append(icono, elemento("span", null, "Ver pago"));
        return enlace;
    }
})();
