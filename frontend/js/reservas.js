// Pagina "Mis reservas y solicitudes recibidas" (HU-30, parte A): lo vigente
// del usuario, en dos pestanas, siempre con su token de acceso:
//   GET  /api/tutoring/v1/reservas?rol=estudiante&estado=  -> «Mis reservas» (HU-21)
//   GET  /api/tutoring/v1/reservas?rol=tutor&estado=       -> «Solicitudes recibidas» (HU-21)
//   POST /api/tutoring/v1/reservas/{id}/confirmar          -> el tutor confirma (HU-22)
//   POST /api/tutoring/v1/reservas/{id}/rechazar           -> el tutor rechaza (HU-22)
// Lo vigente es SOLICITADA y CONFIRMADA: en cada pestana, un GET por estado, en
// paralelo. Lo terminado es del historial (HU-26). Pagar (HU-24) y retirar o
// cancelar (HU-28) llegan en las partes B y C.
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
    // Lo vigente, en palabras. Lo que no esta aqui (lo terminado) no se muestra.
    const ESTADOS = new Map([
        ["SOLICITADA", "Solicitada"],
        ["CONFIRMADA", "Confirmada"],
    ]);
    const MODALIDADES = new Map([
        ["PRESENCIAL", "Presencial"],
        ["EN_LINEA", "En línea"],
    ]);
    // Las palabras del pago de HU-24. «Sin pago» y la falta de estado_pago se
    // deciden en textoDelPago.
    const PAGOS = new Map([
        ["PENDIENTE", "Pendiente"],
        ["PAGADO", "Pagado"],
        ["FALLIDO", "Fallido"],
        ["REEMBOLSADO", "Reembolsado"],
    ]);
    // Cada pestana con su rol en la API y sus elementos en reservas.html.
    const PESTANAS = {
        estudiante: {
            pestana: "pestanaEstudiante",
            panel: "panelEstudiante",
            lista: "listaEstudiante",
            vacio: "vacioEstudiante",
            contador: "contadorEstudiante",
        },
        tutor: {
            pestana: "pestanaTutor",
            panel: "panelTutor",
            lista: "listaTutor",
            vacio: "vacioTutor",
            contador: "contadorTutor",
        },
    };
    // Como la API (HU-22): el lugar o el enlace tiene hasta 300 caracteres y,
    // en linea, empieza con http:// o https://.
    const LARGO_LUGAR = 300;
    const PREFIJOS_ENLACE = ["http://", "https://"];
    // La etiqueta, el ejemplo y el mensaje del campo, segun la modalidad. Los
    // mensajes son los mismos de la API.
    const CAMPO_SIN_MODALIDAD = { etiqueta: "Lugar o enlace", ejemplo: "Elige primero la modalidad." };
    const CAMPO_DE = {
        PRESENCIAL: {
            etiqueta: "Lugar de la tutoría",
            ejemplo: "Por ejemplo: Sede Alameda, biblioteca, sala de estudio 2",
            falta: "Indica el lugar de la tutoría presencial.",
        },
        EN_LINEA: {
            etiqueta: "Enlace de la sesión",
            ejemplo: "Por ejemplo: https://meet.google.com/abc-defg-hij",
            falta: "Indica el enlace de la tutoría en línea.",
        },
    };
    const SIN_MODALIDAD = "Elige la modalidad: presencial o en línea.";
    const ENLACE_INVALIDO = "El enlace de una tutoría en línea tiene que empezar con http:// o https://.";
    // «Rechazar» espera la segunda pulsacion durante 5 segundos.
    const ESPERA_RECHAZO = 5000;
    const SIN_CONEXION =
        "No hay conexión con el servicio de Tutorías. Revisa que el sistema esté levantado.";

    // Cada carga lleva un numero: si dos se cruzan (por ejemplo, al confirmar
    // una y rechazar otra seguidas), solo se dibuja la ultima que se pidio.
    let ultimaCarga = 0;

    document.addEventListener("DOMContentLoaded", iniciar);

    function porId(id) {
        return document.getElementById(id);
    }

    async function iniciar() {
        prepararPestanas();
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
        await cargarReservas();
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

    // Las dos pestanas a la vez (criterio 1): en cada una, un GET con
    // estado=SOLICITADA y otro con estado=CONFIRMADA, los cuatro en paralelo.
    // Si uno falla, no se dibuja ninguna: una pestana no queda a medias sin que
    // se note.
    async function cargarReservas() {
        const carga = ++ultimaCarga;
        const pedidos = [];
        for (const rol of Object.keys(PESTANAS)) {
            for (const estado of ESTADOS.keys()) {
                pedidos.push(pedirTutorias(`/reservas?rol=${rol}&estado=${estado}`));
            }
        }
        let respuestas;
        try {
            respuestas = await Promise.all(pedidos);
        } catch {
            if (carga === ultimaCarga) {
                mostrarAviso("error", SIN_CONEXION);
            }
            return;
        }
        if (carga !== ultimaCarga) {
            return;
        }
        if (respuestas.some((r) => r.estado === 401)) {
            mostrarSinSesion("Tu sesión venció. Vuelve a iniciar sesión para ver tus reservas.");
            return;
        }
        const fallida = respuestas.find((r) => !r.ok);
        if (fallida) {
            mostrarAviso("error", mensajeDeError(fallida.cuerpo, "No se pudieron cargar tus reservas."));
            return;
        }
        const [solicitadas, confirmadas, recibidas, confirmadasComoTutor] = respuestas;
        dibujarPestana("estudiante", vigentes(solicitadas.cuerpo, confirmadas.cuerpo));
        dibujarPestana("tutor", vigentes(recibidas.cuerpo, confirmadasComoTutor.cuerpo));
        porId("conSesion").classList.remove("hidden");
    }

    // Lo solicitado y lo confirmado juntos, del bloque mas proximo al mas
    // lejano. Con el mismo inicio quedan en el orden en que llegaron (sort no
    // cambia el orden de los empates): primero las solicitudes, de la mas nueva
    // a la mas antigua, como las manda la API.
    function vigentes(...cuerpos) {
        return cuerpos
            .flatMap((cuerpo) => (Array.isArray(cuerpo) ? cuerpo : []))
            .filter((reserva) => ESTADOS.has(reserva.estado))
            .sort((a, b) => Date.parse(a.bloque.inicio_en) - Date.parse(b.bloque.inicio_en));
    }

    // ------------------------------------------------------------ pestanas

    // role="tablist", "tab" y "tabpanel": con el clic, y con las flechas,
    // Inicio y Fin, como en el patron de pestanas de WAI-ARIA.
    function prepararPestanas() {
        const roles = Object.keys(PESTANAS);
        for (const rol of roles) {
            porId(PESTANAS[rol].pestana).addEventListener("click", () => elegirPestana(rol));
        }
        porId(PESTANAS.estudiante.pestana).parentElement.addEventListener("keydown", (evento) => {
            const actual = roles.findIndex(
                (rol) => porId(PESTANAS[rol].pestana).getAttribute("aria-selected") === "true"
            );
            const destino = {
                ArrowRight: (actual + 1) % roles.length,
                ArrowLeft: (actual - 1 + roles.length) % roles.length,
                Home: 0,
                End: roles.length - 1,
            }[evento.key];
            if (destino === undefined) {
                return;
            }
            evento.preventDefault();
            elegirPestana(roles[destino]);
            porId(PESTANAS[roles[destino]].pestana).focus();
        });
    }

    function elegirPestana(elegido) {
        for (const [rol, ids] of Object.entries(PESTANAS)) {
            const activa = rol === elegido;
            const pestana = porId(ids.pestana);
            pestana.setAttribute("aria-selected", String(activa));
            pestana.tabIndex = activa ? 0 : -1;
            porId(ids.panel).classList.toggle("hidden", !activa);
        }
    }

    // ------------------------------------------------------------ dibujo

    function dibujarPestana(rol, reservas) {
        const { lista, vacio, contador } = PESTANAS[rol];
        porId(lista).replaceChildren(...reservas.map((reserva) => tarjeta(reserva, rol)));
        porId(vacio).classList.toggle("hidden", reservas.length > 0);
        porId(contador).textContent = String(reservas.length);
    }

    // Una reserva: la asignatura, la otra persona, el dia y las horas en hora
    // de Chile (criterio 3), el estado, la nota, la modalidad y el lugar o el
    // enlace, el monto y el pago.
    function tarjeta(reserva, rol) {
        const clase = reserva.estado.toLowerCase();
        const item = elemento("li", `res-item res-item-${clase}`);

        const asignatura = elemento("div", "res-asignatura");
        asignatura.append(
            elemento("span", "res-sigla", reserva.asignatura.sigla),
            elemento("strong", "res-asignatura-nombre", reserva.asignatura.nombre)
        );
        const cabecera = elemento("div", "res-item-cabecera");
        cabecera.append(
            asignatura,
            elemento("span", `res-estado res-estado-${clase}`, ESTADOS.get(reserva.estado))
        );

        // En «Mis reservas», el tutor; en «Solicitudes recibidas», quien la pidio.
        const comoEstudiante = rol === "estudiante";
        const persona = elemento("p", "res-persona");
        persona.append(
            elemento("span", "res-etiqueta", comoEstudiante ? "Tutor: " : "Estudiante: "),
            nombreCompleto(comoEstudiante ? reserva.tutor : reserva.solicitante)
        );

        item.append(cabecera, persona, elemento("p", "res-cuando", describir(reserva.bloque)));
        if (reserva.nota) {
            const nota = elemento("p", "res-nota");
            nota.append(elemento("span", "res-etiqueta", "Nota para el tutor: "), reserva.nota);
            item.appendChild(nota);
        }
        item.appendChild(datos(reserva));

        // Criterio 2: solo el tutor, y solo mientras la solicitud esta pendiente.
        if (rol === "tutor" && reserva.rol === "tutor" && reserva.estado === "SOLICITADA") {
            item.appendChild(gestion(reserva));
        }
        // HU-24 (parte B de HU-30): «Pagar» y «Ver detalle», al final.
        item.appendChild(enlacesDelPago(reserva, rol));
        return item;
    }

    // La modalidad y el lugar o el enlace (si esta confirmada), el monto y el pago.
    function datos(reserva) {
        const lista = elemento("dl", "res-datos");
        if (reserva.estado === "CONFIRMADA") {
            const enLinea = reserva.modalidad === "EN_LINEA";
            dato(lista, "Modalidad", MODALIDADES.get(reserva.modalidad) || String(reserva.modalidad));
            dato(lista, enLinea ? "Enlace" : "Lugar", lugarOEnlace(reserva));
        }
        dato(lista, "Monto", tarifaEnTexto(reserva.monto));
        dato(lista, "Pago", ...textoDelPago(reserva));
        return lista;
    }

    // El enlace va como enlace solo si la modalidad es EN_LINEA y empieza con
    // https:// o http://: un href con otro esquema, como javascript:, correria
    // codigo en la pagina. En cualquier otro caso, como texto.
    function lugarOEnlace(reserva) {
        const valor = String(reserva.lugar_o_enlace ?? "");
        if (reserva.modalidad !== "EN_LINEA" || !esEnlace(valor)) {
            return valor;
        }
        const enlace = elemento("a", "res-enlace", valor);
        enlace.href = valor;
        enlace.target = "_blank";
        enlace.rel = "noopener noreferrer";
        return enlace;
    }

    // Las cinco palabras de HU-24: «Sin pago» si el monto es 0; si no, la de
    // estado_pago. estado_pago queda en null hasta que Pagos crea el pago (M-10
    // del anexo A): con monto, eso tambien es «Pendiente». En una solicitud con
    // monto se agrega cuando se paga.
    function textoDelPago(reserva) {
        if (Number(reserva.monto) === 0) {
            return ["Sin pago"];
        }
        const estado = reserva.estado_pago;
        const texto = estado === null || estado === undefined ? "Pendiente" : PAGOS.get(estado) || estado;
        if (reserva.estado !== "SOLICITADA") {
            return [texto];
        }
        return [texto, elemento("small", "res-pago-nota", "Se paga cuando el tutor confirme.")];
    }

    // ------------------------------------------------------------ confirmar y rechazar

    // Criterio 2: «Confirmar» abre, en la misma tarjeta, la modalidad y el
    // lugar o el enlace; «Rechazar» pide una segunda pulsacion.
    function gestion(reserva) {
        const id = reserva.id;
        const quien = `la solicitud de ${nombreCompleto(reserva.solicitante)} del ${describir(reserva.bloque)}`;

        const abrir = boton("Confirmar", "fa-solid fa-check", "btn-primary res-boton-principal", `Confirmar ${quien}`);
        const rechazar = boton("Rechazar", "fa-solid fa-xmark", "res-boton res-boton-peligro", `Rechazar ${quien}`);
        const botones = elemento("div", "res-acciones");
        botones.append(abrir, rechazar);

        // Los errores de esta tarjeta que no vuelven a cargar la lista.
        const errorTarjeta = mensajeDeCampo(`res-error-tarjeta-${id}`);
        errorTarjeta.setAttribute("role", "alert");

        const confirmacion = formularioDeConfirmacion(reserva, quien);

        // La primera pulsacion de «Rechazar» cambia el texto; la segunda, dentro
        // de 5 segundos, rechaza. Sin ventanas del navegador.
        let espera = null;
        const desarmar = () => {
            clearTimeout(espera);
            espera = null;
            rechazar.classList.remove("res-boton-armado");
            cambiarTexto(rechazar, "Rechazar", `Rechazar ${quien}`);
        };
        rechazar.addEventListener("click", async () => {
            if (rechazar.disabled) {
                return;
            }
            ocultarMensaje(errorTarjeta);
            if (!espera) {
                rechazar.classList.add("res-boton-armado");
                cambiarTexto(rechazar, "¿Rechazar? Pulsa de nuevo", `¿Rechazar ${quien}? Pulsa de nuevo`);
                espera = setTimeout(desarmar, ESPERA_RECHAZO);
                return;
            }
            desarmar();
            abrir.disabled = true;
            rechazar.disabled = true;
            try {
                await enviarRechazo(id, errorTarjeta);
            } finally {
                abrir.disabled = false;
                rechazar.disabled = false;
            }
        });

        abrir.addEventListener("click", () => {
            desarmar();
            ocultarMensaje(errorTarjeta);
            botones.classList.add("hidden");
            confirmacion.abrir();
        });
        confirmacion.alCerrar(() => {
            botones.classList.remove("hidden");
            abrir.focus();
        });

        const contenedor = elemento("div", "res-gestion");
        contenedor.append(botones, errorTarjeta, confirmacion.formulario);
        return contenedor;
    }

    // El formulario de la confirmacion: la modalidad con dos radios, el lugar
    // o el enlace, «Confirmar tutoria» y «Cerrar».
    function formularioDeConfirmacion(reserva, quien) {
        const id = reserva.id;
        // novalidate: la validacion la hace la pagina, con sus mensajes.
        const formulario = elemento("form", "res-formulario hidden");
        formulario.noValidate = true;
        formulario.setAttribute("aria-label", `Confirmar ${quien}`);

        // La modalidad: ninguna elegida al abrir.
        const grupo = elemento("fieldset", "res-modalidad");
        grupo.appendChild(elemento("legend", null, "Modalidad"));
        const radios = [];
        for (const [valor, texto] of MODALIDADES) {
            const radio = document.createElement("input");
            radio.type = "radio";
            radio.name = `res-modalidad-${id}`;
            radio.value = valor;
            const opcion = elemento("label", "res-opcion");
            opcion.append(radio, elemento("span", null, texto));
            grupo.appendChild(opcion);
            radios.push(radio);
        }
        const errorModalidad = mensajeDeCampo(`res-error-modalidad-${id}`);
        grupo.setAttribute("aria-describedby", errorModalidad.id);
        grupo.appendChild(errorModalidad);

        // El lugar o el enlace: la etiqueta y el ejemplo cambian con la modalidad.
        const campo = document.createElement("input");
        campo.type = "text";
        campo.id = `res-lugar-${id}`;
        campo.maxLength = LARGO_LUGAR;
        campo.autocomplete = "off";
        const etiqueta = elemento("label");
        etiqueta.htmlFor = campo.id;
        const ejemplo = elemento("small", "res-ayuda");
        ejemplo.id = `res-ejemplo-${id}`;
        const errorLugar = mensajeDeCampo(`res-error-lugar-${id}`);
        campo.setAttribute("aria-describedby", `${ejemplo.id} ${errorLugar.id}`);
        const caja = elemento("div", "res-campo");
        caja.append(etiqueta, campo, ejemplo, errorLugar);

        // Lo que la API rechaza sin ser de la modalidad ni del campo.
        const errorEnvio = mensajeDeCampo(`res-error-envio-${id}`);
        errorEnvio.setAttribute("role", "alert");

        const enviar = elemento("button", "btn-primary", "Confirmar tutoría");
        enviar.type = "submit";
        const cerrar = elemento("button", "res-boton", "Cerrar");
        cerrar.type = "button";
        const acciones = elemento("div", "res-form-acciones");
        acciones.append(enviar, cerrar);

        formulario.append(grupo, caja, errorEnvio, acciones);

        const modalidadElegida = () => radios.find((radio) => radio.checked)?.value || null;
        const ponerCampo = () => {
            const modalidad = modalidadElegida();
            const textos = CAMPO_DE[modalidad] || CAMPO_SIN_MODALIDAD;
            etiqueta.textContent = textos.etiqueta;
            ejemplo.textContent = textos.ejemplo;
            campo.inputMode = modalidad === "EN_LINEA" ? "url" : "text";
        };
        ponerCampo();
        for (const radio of radios) {
            radio.addEventListener("change", () => {
                ponerCampo();
                ocultarMensaje(errorModalidad, grupo);
                ocultarMensaje(errorLugar, campo);
            });
        }
        campo.addEventListener("input", () => ocultarMensaje(errorLugar, campo));

        let alCerrar = () => {};
        cerrar.addEventListener("click", () => {
            formulario.reset();
            ponerCampo();
            ocultarMensaje(errorModalidad, grupo);
            ocultarMensaje(errorLugar, campo);
            ocultarMensaje(errorEnvio);
            formulario.classList.add("hidden");
            alCerrar();
        });

        formulario.addEventListener("submit", async (evento) => {
            evento.preventDefault();
            if (enviar.disabled) {
                return;
            }
            ocultarMensaje(errorEnvio);

            // Lo mismo que revisa la API antes de tocar la base: la modalidad,
            // un texto que no quede vacio y, en linea, http:// o https://. Si
            // hay algo que corregir, no sale ninguna peticion.
            const modalidad = modalidadElegida();
            const texto = campo.value.trim();
            if (!modalidad) {
                mostrarMensaje(errorModalidad, grupo, SIN_MODALIDAD);
                ocultarMensaje(errorLugar, campo);
                radios[0].focus();
                return;
            }
            const problema = problemaDelLugar(modalidad, texto);
            if (problema) {
                mostrarMensaje(errorLugar, campo, problema);
                campo.focus();
                return;
            }

            const cuerpo = JSON.stringify({ modalidad, lugar_o_enlace: texto });
            enviar.disabled = true;
            cerrar.disabled = true;
            try {
                await enviarConfirmacion(id, cuerpo, { campo, errorLugar, errorEnvio });
            } finally {
                enviar.disabled = false;
                cerrar.disabled = false;
            }
        });

        return {
            formulario,
            abrir() {
                formulario.classList.remove("hidden");
                radios[0].focus();
            },
            alCerrar(funcion) {
                alCerrar = funcion;
            },
        };
    }

    function problemaDelLugar(modalidad, texto) {
        if (!texto) {
            return CAMPO_DE[modalidad].falta;
        }
        if (modalidad === "EN_LINEA" && !esEnlace(texto)) {
            return ENLACE_INVALIDO;
        }
        return null;
    }

    // POST /confirmar. Con 200, el aviso y las dos pestanas de nuevo. Con un 404
    // o un 409, la reserva cambio desde que se cargo la lista: el mensaje de la
    // API y las pestanas de nuevo.
    async function enviarConfirmacion(id, cuerpo, campos) {
        let r;
        try {
            r = await pedirTutorias(`/reservas/${encodeURIComponent(id)}/confirmar`, {
                method: "POST",
                body: cuerpo,
            });
        } catch {
            mostrarMensaje(campos.errorEnvio, null, SIN_CONEXION);
            return;
        }
        if (r.ok) {
            mostrarAviso(
                "exito",
                "Tutoría confirmada. Si había otras solicitudes para ese horario, quedaron rechazadas."
            );
            await cargarReservas();
            return;
        }
        if (r.estado === 401) {
            mostrarSinSesion("Tu sesión venció. Vuelve a iniciar sesión para confirmar la tutoría.");
            return;
        }
        const texto = mensajeDeError(r.cuerpo, "No se pudo confirmar la tutoría.");
        if (r.estado === 404 || r.estado === 409) {
            mostrarAviso("error", texto);
            await cargarReservas();
        } else if (r.cuerpo?.codigo === "lugar_o_enlace_invalido") {
            mostrarMensaje(campos.errorLugar, campos.campo, texto);
            campos.campo.focus();
        } else {
            mostrarMensaje(campos.errorEnvio, null, texto);
        }
    }

    // POST /rechazar, sin cuerpo. Igual que la confirmacion.
    async function enviarRechazo(id, errorTarjeta) {
        let r;
        try {
            r = await pedirTutorias(`/reservas/${encodeURIComponent(id)}/rechazar`, { method: "POST" });
        } catch {
            mostrarMensaje(errorTarjeta, null, SIN_CONEXION);
            return;
        }
        if (r.ok) {
            mostrarAviso("exito", "Solicitud rechazada.");
            await cargarReservas();
            return;
        }
        if (r.estado === 401) {
            mostrarSinSesion("Tu sesión venció. Vuelve a iniciar sesión para rechazar la solicitud.");
            return;
        }
        const texto = mensajeDeError(r.cuerpo, "No se pudo rechazar la solicitud.");
        if (r.estado === 404 || r.estado === 409) {
            mostrarAviso("error", texto);
            await cargarReservas();
        } else {
            mostrarMensaje(errorTarjeta, null, texto);
        }
    }

    // ------------------------------------------------------------ avisos

    function mostrarAviso(tipo, texto) {
        const caja = porId("aviso");
        caja.className = `res-aviso res-aviso-${tipo}`;
        caja.textContent = texto;
        caja.scrollIntoView({ block: "nearest" });
    }

    function ocultarAviso() {
        const caja = porId("aviso");
        caja.className = "res-aviso hidden";
        caja.textContent = "";
    }

    function mostrarSinSesion(texto) {
        porId("conSesion").classList.add("hidden");
        porId("sinSesion").classList.remove("hidden");
        if (texto) {
            porId("sinSesionTexto").textContent = texto;
        }
        ocultarAviso();
    }

    // El mensaje junto a lo que hay que corregir.
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

    // ------------------------------------------------------------ ayudas

    function elemento(etiqueta, clase, texto) {
        const nodo = document.createElement(etiqueta);
        if (clase) nodo.className = clase;
        if (texto !== undefined) nodo.textContent = texto;
        return nodo;
    }

    // Un boton con icono. El texto va en su propio span, para cambiarlo.
    function boton(texto, icono, clase, etiqueta) {
        const nodo = elemento("button", clase);
        nodo.type = "button";
        nodo.setAttribute("aria-label", etiqueta);
        const simbolo = elemento("i", icono);
        simbolo.setAttribute("aria-hidden", "true");
        nodo.append(simbolo, elemento("span", null, texto));
        return nodo;
    }

    function cambiarTexto(nodo, texto, etiqueta) {
        nodo.querySelector("span").textContent = texto;
        nodo.setAttribute("aria-label", etiqueta);
    }

    function mensajeDeCampo(id) {
        const nodo = elemento("p", "res-error hidden");
        nodo.id = id;
        return nodo;
    }

    // Una fila del detalle: el termino y su valor (textos o nodos).
    function dato(lista, termino, ...valor) {
        const fila = elemento("div", "res-dato");
        const descripcion = elemento("dd");
        descripcion.append(...valor);
        fila.append(elemento("dt", null, termino), descripcion);
        lista.appendChild(fila);
    }

    function esEnlace(texto) {
        return PREFIJOS_ENLACE.some((prefijo) => texto.startsWith(prefijo));
    }

    function nombreCompleto(persona) {
        return `${persona.nombre} ${persona.apellido}`;
    }

    // Copiada de tutor.js: "Gratis" si es 0; si no, en pesos con el separador
    // de miles chileno: $5.000. El punto se pone a mano, porque no todos los
    // navegadores lo ponen en los numeros de cuatro cifras.
    function tarifaEnTexto(tarifa) {
        const monto = Math.round(Number(tarifa));
        if (monto === 0) {
            return "Gratis";
        }
        return `$${String(monto).replace(/\B(?=(\d{3})+(?!\d))/g, ".")}`;
    }

    function fechaDeChile(iso) {
        return new Date(iso).toLocaleString("es-CL", FORMATO_FECHA);
    }

    function horaDeChile(iso) {
        return new Date(iso).toLocaleString("es-CL", FORMATO_HORA);
    }

    // "miércoles, 11 de noviembre de 2026, de 18:00 a 19:00", como en
    // disponibilidad.js, y la fecha del termino si es otro dia.
    function describir(bloque) {
        const inicio = bloque.inicio_en;
        const fin = bloque.fin_en;
        const texto = `${fechaDeChile(inicio)}, de ${horaDeChile(inicio)} a ${horaDeChile(fin)}`;
        const otroDia = fechaDeChile(fin) !== fechaDeChile(inicio);
        return otroDia ? `${texto} (termina el ${fechaDeChile(fin)})` : texto;
    }

    // ------------------------------------------------------------ pagar y ver detalle (HU-24)

    // El pago sin resolver: todavia sin pago (null), PENDIENTE o FALLIDO.
    const PAGO_SIN_RESOLVER = new Set([null, "PENDIENTE", "FALLIDO"]);

    // HU-30, criterio 1: en «Mis reservas», una tutoria CONFIRMADA con monto y
    // el pago sin resolver tiene «Pagar» («Reintentar el pago» si fallo).
    // HU-24, criterio 3: cada tarjeta, en las dos pestanas, tiene «Ver
    // detalle». Los dos llevan a pago.html?reserva=<id>.
    function enlacesDelPago(reserva, rol) {
        const destino = `pago.html?reserva=${encodeURIComponent(reserva.id)}`;
        const tutoria = `la tutoría de ${reserva.asignatura.nombre}, ${describir(reserva.bloque)}`;
        const enlaces = elemento("div", "res-enlaces");
        if (rol === "estudiante" && reserva.rol === "estudiante" && sePuedePagar(reserva)) {
            const reintento = reserva.estado_pago === "FALLIDO";
            const texto = reintento ? "Reintentar el pago" : "Pagar";
            enlaces.appendChild(
                enlaceConIcono(
                    destino,
                    texto,
                    reintento ? "fa-solid fa-rotate-right" : "fa-solid fa-wallet",
                    "btn-primary res-boton-principal",
                    reintento ? `Reintentar el pago de ${tutoria}` : `Pagar ${tutoria}`
                )
            );
        }
        enlaces.appendChild(
            enlaceConIcono(
                destino,
                "Ver detalle",
                "fa-solid fa-circle-info",
                "res-boton",
                `Ver detalle de ${tutoria}`
            )
        );
        return enlaces;
    }

    function sePuedePagar(reserva) {
        return (
            reserva.estado === "CONFIRMADA" &&
            Number(reserva.monto) > 0 &&
            PAGO_SIN_RESOLVER.has(reserva.estado_pago ?? null)
        );
    }

    // Un enlace con icono y aspecto de boton. El texto va en su propio span.
    function enlaceConIcono(destino, texto, icono, clase, etiqueta) {
        const nodo = elemento("a", clase);
        nodo.href = destino;
        nodo.setAttribute("aria-label", etiqueta);
        const simbolo = elemento("i", icono);
        simbolo.setAttribute("aria-hidden", "true");
        nodo.append(simbolo, elemento("span", null, texto));
        return nodo;
    }
})();
