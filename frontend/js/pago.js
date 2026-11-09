// Pagina "Detalle y pago" (HU-24 y HU-30, parte B): una reserva y su pago
// simulado, en pago.html?reserva=<id>. Siempre con el token de acceso:
//   GET  /api/tutoring/v1/reservas/{id}           -> la reserva (HU-21)
//   GET  /api/payments/v1/pagos?reserva={id}       -> su pago, con los intentos (HU-23)
//   POST /api/payments/v1/pagos                    -> crea el pago, si no hay (HU-23)
//   POST /api/payments/v1/pagos/{pago_id}/simular  -> simula el cobro (HU-23)
// El pago es simulado: no se cobra dinero real ni se piden datos de tarjeta,
// y la pagina no tiene ningun campo de tarjeta (criterio 1).
// Las fechas llegan en UTC y se muestran en hora de Chile (America/Santiago).
// Los datos se escriben con textContent, nunca con innerHTML.

// El encabezado (sesion.js) y esta pagina piden la sesion al mismo tiempo: la
// renovacion se comparte en Sesion.renovar (sesion.js).

// El resto va dentro de una funcion, para no chocar con los nombres globales
// de sesion.js (Sesion, IDENTIDAD, mensajeDeError, avisar...).
(() => {
    "use strict";

    const TUTORIAS = "/api/tutoring/v1";
    const PAGOS = "/api/payments/v1";
    const ZONA_CHILE = "America/Santiago";
    // Como en tutor.js: el id de la direccion se revisa antes de usarlo.
    const FORMATO_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
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
    const ESTADOS = new Map([
        ["SOLICITADA", "Solicitada"],
        ["CONFIRMADA", "Confirmada"],
        ["REALIZADA", "Realizada"],
        ["EVALUADA", "Evaluada"],
        ["CANCELADA", "Cancelada"],
        ["RECHAZADA", "Rechazada"],
        ["EXPIRADA", "Expirada"],
    ]);
    const MODALIDADES = new Map([
        ["PRESENCIAL", "Presencial"],
        ["EN_LINEA", "En línea"],
    ]);
    // Las cinco palabras del pago (criterio 3), las mismas de reservas.js.
    // SIN_PAGO no viene de la API: es una tutoria de monto 0.
    const PALABRAS_PAGO = new Map([
        ["SIN_PAGO", "Sin pago"],
        ["PENDIENTE", "Pendiente"],
        ["PAGADO", "Pagado"],
        ["FALLIDO", "Fallido"],
        ["REEMBOLSADO", "Reembolsado"],
    ]);
    const TIPOS_DE_INTENTO = new Map([
        ["COBRO", "Cobro"],
        ["REEMBOLSO", "Reembolso"],
    ]);
    const RESULTADOS_DE_INTENTO = new Map([
        ["EXITOSO", "Aprobado"],
        ["FALLIDO", "Rechazado"],
    ]);
    // Se paga una reserva CONFIRMADA, REALIZADA o EVALUADA: una tutoria que ya
    // paso tambien se paga, porque el pago no depende de la sesion (HU-23,
    // criterio 7).
    const ESTADOS_PAGABLES = new Set(["CONFIRMADA", "REALIZADA", "EVALUADA"]);
    const ESTADOS_NO_VIGENTES = new Set(["CANCELADA", "RECHAZADA", "EXPIRADA"]);
    // El aviso, segun el estado del pago que responde la simulacion.
    const AVISOS_DEL_RESULTADO = new Map([
        ["PAGADO", ["exito", "Pago aprobado. Tu tutoría quedó pagada."]],
        ["FALLIDO", ["advertencia", "El pago fue rechazado (simulado). Puedes reintentarlo."]],
        [
            "REEMBOLSADO",
            [
                "advertencia",
                "La tutoría se canceló mientras pagabas: el pago quedó reembolsado (simulado).",
            ],
        ],
    ]);
    const REINTENTAR = "El último intento fue rechazado: puedes reintentar.";
    const PREFIJOS_ENLACE = ["http://", "https://"];
    const ENLACE_INVALIDO =
        "El enlace no es válido. Abre la tutoría desde «Mis reservas» o desde tu historial.";
    const SIN_PAGOS =
        "No se pudo consultar el servicio de Pagos: el estado del pago es el último que guardó Tutorías.";
    const PAGOS_NO_RESPONDE = "El servicio de Pagos no respondió. Intenta de nuevo en unos minutos.";
    const SIN_CONEXION_TUTORIAS =
        "No hay conexión con el servicio de Tutorías. Revisa que el sistema esté levantado.";
    const SIN_CONEXION_PAGOS =
        "No hay conexión con el servicio de Pagos. Revisa que el sistema esté levantado.";

    // El id de la reserva, ya revisado.
    let reservaId = null;
    // El pago que se dibujo: null si la reserva no tiene, o si Pagos no respondio.
    let pagoActual = null;
    // Mientras se paga (y despues, mientras se vuelve a cargar), los dos
    // botones quedan deshabilitados.
    let ocupado = false;
    // Cada carga lleva un numero: si dos se cruzan, solo se dibuja la ultima.
    let ultimaCarga = 0;

    document.addEventListener("DOMContentLoaded", iniciar);

    function porId(id) {
        return document.getElementById(id);
    }

    async function iniciar() {
        // Si ?reserva= no es un uuid, la pagina lo dice y no llama a la API.
        const id = new URLSearchParams(window.location.search).get("reserva") || "";
        if (!FORMATO_UUID.test(id)) {
            porId("cargando").classList.add("hidden");
            mostrarNoEncontrada(ENLACE_INVALIDO);
            return;
        }
        // La ruta de Tutorias acepta el uuid solo en minusculas (ReservaId).
        reservaId = id.toLowerCase();
        porId("simularAprobado").addEventListener("click", () => simular("EXITOSO"));
        porId("simularRechazado").addEventListener("click", () => simular("FALLIDO"));

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
        await cargar();
        porId("cargando").classList.add("hidden");
    }

    // fetch a Tutorias o a Pagos con el token de acceso. Si vencio (dura 30
    // minutos), se renueva una vez con la cookie y se reintenta, como en
    // reservas.js. Sin conexion, lanza (fetch rechaza).
    async function pedir(servicio, ruta, opciones = {}) {
        const enviar = () =>
            fetch(servicio + ruta, {
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

    // Igual, pero sin conexion responde estado 0 en vez de lanzar: asi un
    // servicio caido no impide mostrar lo que respondio el otro.
    async function pedirSinLanzar(servicio, ruta) {
        try {
            return await pedir(servicio, ruta);
        } catch {
            return { ok: false, estado: 0, cuerpo: null };
        }
    }

    // ------------------------------------------------------------ carga

    // La reserva (Tutorias) y su pago (Pagos), en paralelo. El estado del pago
    // sale de Pagos; si Pagos no responde, del estado_pago que guarda Tutorias,
    // con un aviso (criterio 3).
    async function cargar() {
        const carga = ++ultimaCarga;
        const id = encodeURIComponent(reservaId);
        const [deTutorias, dePagos] = await Promise.all([
            pedirSinLanzar(TUTORIAS, `/reservas/${id}`),
            pedirSinLanzar(PAGOS, `/pagos?reserva=${id}`),
        ]);
        if (carga !== ultimaCarga) {
            return;
        }
        if (deTutorias.estado === 401) {
            mostrarSinSesion("Tu sesión venció. Vuelve a iniciar sesión para ver la tutoría.");
            return;
        }
        if (deTutorias.estado === 0) {
            mostrarAviso("error", SIN_CONEXION_TUTORIAS);
            return;
        }
        // 404 reserva_no_encontrada: no existe o es de otras personas.
        if (deTutorias.estado === 404) {
            mostrarNoEncontrada(mensajeDeError(deTutorias.cuerpo, "No encontramos esa tutoría."));
            return;
        }
        if (!deTutorias.ok || !esObjeto(deTutorias.cuerpo)) {
            mostrarAviso("error", mensajeDeError(deTutorias.cuerpo, "No se pudo cargar la tutoría."));
            return;
        }
        const reserva = deTutorias.cuerpo;

        // Pagos: 200 con el pago, o 404 pago_no_encontrado si todavia no hay.
        // Cualquier otra respuesta (sin conexion, 5xx, el 502 del gateway, o un
        // 401 que siguio despues de renovar) es que Pagos no respondio.
        let pago = null;
        let pagosRespondio = true;
        if (dePagos.ok && esObjeto(dePagos.cuerpo)) {
            pago = dePagos.cuerpo;
        } else if (!(dePagos.estado === 404 && dePagos.cuerpo?.codigo === "pago_no_encontrado")) {
            pagosRespondio = false;
        }
        pagoActual = pago;
        dibujarReserva(reserva);
        dibujarPago(reserva, pago, estadoDelPago(reserva, pago, pagosRespondio));
        porId("noEncontrada").classList.add("hidden");
        porId("sinSesion").classList.add("hidden");
        porId("conSesion").classList.remove("hidden");
        if (!pagosRespondio) {
            mostrarAviso("advertencia", SIN_PAGOS);
        }
    }

    // El estado del pago (criterio 3): con un pago, el suyo. Si Pagos responde
    // que no hay, «Sin pago» con monto 0 y «Pendiente» si no. Si Pagos no
    // respondio, el estado_pago de la reserva, con la regla de reservas.js
    // (null con monto tambien es «Pendiente»).
    function estadoDelPago(reserva, pago, pagosRespondio) {
        if (pago) {
            return pago.estado;
        }
        if (Number(reserva.monto) === 0) {
            return "SIN_PAGO";
        }
        if (pagosRespondio) {
            return "PENDIENTE";
        }
        return reserva.estado_pago ?? "PENDIENTE";
    }

    // ------------------------------------------------------------ dibujo

    // La asignatura, la otra persona, el dia y las horas en hora de Chile, el
    // estado y, si esta confirmada, la modalidad y el lugar o el enlace.
    function dibujarReserva(reserva) {
        const clase = String(reserva.estado).toLowerCase();
        const asignatura = elemento("div", "res-asignatura");
        asignatura.append(
            elemento("span", "res-sigla", reserva.asignatura.sigla),
            elemento("strong", "res-asignatura-nombre", reserva.asignatura.nombre)
        );
        const cabecera = elemento("div", "res-item-cabecera");
        cabecera.append(
            asignatura,
            elemento(
                "span",
                `res-estado res-estado-${clase}`,
                ESTADOS.get(reserva.estado) || String(reserva.estado)
            )
        );

        // Para quien la pidio, el tutor; para el tutor, quien la pidio.
        const comoEstudiante = reserva.rol === "estudiante";
        const persona = elemento("p", "res-persona");
        persona.append(
            elemento("span", "res-etiqueta", comoEstudiante ? "Tutor: " : "Estudiante: "),
            nombreCompleto(comoEstudiante ? reserva.tutor : reserva.solicitante)
        );

        const partes = [cabecera, persona, elemento("p", "res-cuando", describir(reserva.bloque))];
        if (reserva.estado === "CONFIRMADA") {
            const lista = elemento("dl", "res-datos");
            const enLinea = reserva.modalidad === "EN_LINEA";
            dato(lista, "Modalidad", MODALIDADES.get(reserva.modalidad) || String(reserva.modalidad));
            dato(lista, enLinea ? "Enlace" : "Lugar", lugarOEnlace(reserva));
            partes.push(lista);
        }
        porId("detalleReserva").replaceChildren(...partes);
    }

    // El monto, el estado del pago, los botones o el texto que explica por
    // que no hay, y los intentos.
    function dibujarPago(reserva, pago, estadoPago) {
        const datos = porId("datosPago");
        datos.replaceChildren();
        dato(datos, "Monto", tarifaEnTexto(reserva.monto));
        const clase = String(estadoPago).toLowerCase().replace("_", "-");
        dato(
            datos,
            "Pago",
            elemento(
                "span",
                `res-pago-estado res-pago-${clase}`,
                PALABRAS_PAGO.get(estadoPago) || String(estadoPago)
            )
        );

        const conBotones = sePuedePagar(reserva, estadoPago);
        let texto = null;
        if (conBotones) {
            texto = estadoPago === "FALLIDO" ? REINTENTAR : null;
        } else {
            texto = porQueNoSePaga(reserva, estadoPago);
        }
        const parrafo = porId("textoPago");
        parrafo.textContent = texto || "";
        parrafo.classList.toggle("hidden", !texto);
        porId("botonesPago").classList.toggle("hidden", !conBotones);
        ponerOcupado(ocupado);

        dibujarIntentos(pago ? pago.intentos : []);
    }

    // Los botones aparecen solo para quien pidio la tutoria, con la reserva
    // CONFIRMADA, REALIZADA o EVALUADA, monto mayor que 0 y el pago ni PAGADO
    // ni REEMBOLSADO (criterios 1 y 2).
    function sePuedePagar(reserva, estadoPago) {
        return (
            reserva.rol === "estudiante" &&
            ESTADOS_PAGABLES.has(reserva.estado) &&
            Number(reserva.monto) > 0 &&
            estadoPago !== "PAGADO" &&
            estadoPago !== "REEMBOLSADO"
        );
    }

    // Sin botones, el primer texto que corresponda.
    function porQueNoSePaga(reserva, estadoPago) {
        if (reserva.rol === "tutor") {
            return "El pago lo hace el estudiante.";
        }
        if (Number(reserva.monto) === 0) {
            return "Esta tutoría es gratuita: no tiene pago.";
        }
        if (estadoPago === "PAGADO") {
            return "Esta tutoría ya está pagada.";
        }
        if (estadoPago === "REEMBOLSADO") {
            return "El pago fue reembolsado (simulado).";
        }
        if (reserva.estado === "SOLICITADA") {
            return "Se paga cuando el tutor confirme la tutoría.";
        }
        if (ESTADOS_NO_VIGENTES.has(reserva.estado)) {
            return "Esta tutoría ya no está vigente: no se puede pagar.";
        }
        return null;
    }

    // Los intentos, si hay, en el orden en que los manda Pagos: del mas nuevo
    // al mas antiguo.
    function dibujarIntentos(intentos) {
        const lista = Array.isArray(intentos) ? intentos : [];
        porId("listaIntentos").replaceChildren(...lista.map(intento));
        porId("intentos").classList.toggle("hidden", lista.length === 0);
    }

    // Un intento: la fecha y la hora de Chile, Cobro o Reembolso, Aprobado o
    // Rechazado, y el mensaje, si trae.
    function intento(datos) {
        const item = elemento("li", "res-intento");
        const aprobado = datos.resultado === "EXITOSO";
        const linea = elemento("p", "res-intento-linea");
        linea.append(
            elemento("span", "res-intento-tipo", TIPOS_DE_INTENTO.get(datos.tipo) || String(datos.tipo)),
            elemento(
                "span",
                `res-intento-resultado ${aprobado ? "res-intento-aprobado" : "res-intento-rechazado"}`,
                RESULTADOS_DE_INTENTO.get(datos.resultado) || String(datos.resultado)
            )
        );
        item.append(elemento("p", "res-intento-cuando", momentoDeChile(datos.creado_en)), linea);
        if (datos.mensaje) {
            item.appendChild(elemento("p", "res-intento-mensaje", datos.mensaje));
        }
        return item;
    }

    // ------------------------------------------------------------ pagar

    // «Simular pago aprobado» o «Simular pago rechazado». Si todavia no hay
    // pago, primero POST /pagos (201, o 200 con el que ya habia) y despues
    // POST /pagos/{id}/simular.
    async function simular(resultado) {
        if (ocupado) {
            return;
        }
        ponerOcupado(true);
        ocultarAviso();
        try {
            await pagar(resultado);
        } finally {
            ponerOcupado(false);
        }
    }

    async function pagar(resultado) {
        let pago = pagoActual;
        if (!pago) {
            pago = await enviarAPagos("/pagos", { reserva_id: reservaId });
            if (!pago) {
                return;
            }
        }
        const simulado = await enviarAPagos(`/pagos/${encodeURIComponent(pago.id)}/simular`, {
            resultado,
        });
        if (!simulado) {
            return;
        }
        // El aviso, segun el estado que respondio Pagos, y despues la reserva
        // y el pago de nuevo.
        const aviso = AVISOS_DEL_RESULTADO.get(simulado.estado);
        if (aviso) {
            mostrarAviso(...aviso);
        }
        await cargar();
    }

    // Un POST a Pagos. Devuelve el pago, o null si hubo un error, que ya quedo
    // en el aviso con el mensaje de la API. Con un 409, la reserva o el pago
    // cambiaron: tambien se vuelven a cargar.
    async function enviarAPagos(ruta, cuerpo) {
        let r;
        try {
            r = await pedir(PAGOS, ruta, { method: "POST", body: JSON.stringify(cuerpo) });
        } catch {
            mostrarAviso("error", SIN_CONEXION_PAGOS);
            return null;
        }
        if (r.ok && esObjeto(r.cuerpo)) {
            return r.cuerpo;
        }
        if (r.estado === 401) {
            mostrarSinSesion("Tu sesión venció. Vuelve a iniciar sesión para pagar la tutoría.");
            return null;
        }
        mostrarAviso("error", mensajeDeError(r.cuerpo, PAGOS_NO_RESPONDE));
        if (r.estado === 409) {
            await cargar();
        }
        return null;
    }

    function ponerOcupado(valor) {
        ocupado = valor;
        porId("simularAprobado").disabled = valor;
        porId("simularRechazado").disabled = valor;
        porId("botonesPago").setAttribute("aria-busy", String(valor));
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
        porId("noEncontrada").classList.add("hidden");
        porId("sinSesion").classList.remove("hidden");
        if (texto) {
            porId("sinSesionTexto").textContent = texto;
        }
        ocultarAviso();
    }

    // El enlace no sirve, o la reserva no existe o es de otras personas.
    function mostrarNoEncontrada(texto) {
        porId("conSesion").classList.add("hidden");
        porId("noEncontradaTexto").textContent = texto;
        porId("noEncontrada").classList.remove("hidden");
    }

    // ------------------------------------------------------------ ayudas

    function elemento(etiqueta, clase, texto) {
        const nodo = document.createElement(etiqueta);
        if (clase) nodo.className = clase;
        if (texto !== undefined) nodo.textContent = texto;
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

    function esObjeto(valor) {
        return typeof valor === "object" && valor !== null && !Array.isArray(valor);
    }

    // La regla de reservas.js: el enlace va como enlace solo si la modalidad
    // es EN_LINEA y empieza con https:// o http://. Un href con otro esquema,
    // como javascript:, correria codigo en la pagina. Si no, como texto.
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

    function esEnlace(texto) {
        return PREFIJOS_ENLACE.some((prefijo) => texto.startsWith(prefijo));
    }

    function nombreCompleto(persona) {
        return `${persona.nombre} ${persona.apellido}`;
    }

    // Como en reservas.js: "Gratis" si es 0; si no, en pesos con el separador
    // de miles chileno: $5.000.
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
    // reservas.js, y la fecha del termino si es otro dia.
    function describir(bloque) {
        const inicio = bloque.inicio_en;
        const fin = bloque.fin_en;
        const texto = `${fechaDeChile(inicio)}, de ${horaDeChile(inicio)} a ${horaDeChile(fin)}`;
        const otroDia = fechaDeChile(fin) !== fechaDeChile(inicio);
        return otroDia ? `${texto} (termina el ${fechaDeChile(fin)})` : texto;
    }

    // "lunes, 28 de septiembre de 2026, 07:01": cuando se registro un intento.
    function momentoDeChile(iso) {
        return `${fechaDeChile(iso)}, ${horaDeChile(iso)}`;
    }
})();
