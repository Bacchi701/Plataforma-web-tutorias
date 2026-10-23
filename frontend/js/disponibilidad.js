// Pagina "Mi disponibilidad" (HU-15): el tutor publica, edita y elimina sus
// bloques con la API de Tutorias, siempre con su token de acceso:
//   GET    /api/tutoring/v1/disponibilidad       -> sus bloques que no han terminado
//   POST   /api/tutoring/v1/disponibilidad       -> publica uno
//   PATCH  /api/tutoring/v1/disponibilidad/{id}  -> lo cambia (libre y sin solicitudes)
//   DELETE /api/tutoring/v1/disponibilidad/{id}  -> lo elimina
// Las horas se escriben y se muestran en hora de Chile, este donde este el
// computador, y viajan en UTC (toISOString) (criterio 6, RNF-08).
// Los datos se escriben con textContent, nunca con innerHTML.

// El encabezado (sesion.js) y esta pagina piden la sesion al mismo tiempo, y
// dos /refresh simultaneos gastan la misma renovacion: el segundo recibe 401 y
// su parte de la pagina se queda sin sesion. Mientras haya una renovacion en
// curso, las demas llamadas esperan esa misma respuesta.
// Es el mismo bloque de perfil.js (HU-10): despues del 23-10 los dos pasan a sesion.js.
const renovarSinCompartir = Sesion.renovar;
let renovacionEnCurso = null;
Sesion.renovar = function () {
    if (!renovacionEnCurso) {
        renovacionEnCurso = renovarSinCompartir.call(Sesion).finally(() => {
            renovacionEnCurso = null;
        });
    }
    return renovacionEnCurso;
};

// El resto va dentro de una funcion, para no chocar con los nombres globales
// de sesion.js (Sesion, mensajeDeError, avisar...).
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
    // Para los campos date y time: "2026-10-22" y "18:00", en hora de Chile.
    const PARTES_DE_CHILE = new Intl.DateTimeFormat("en-CA", {
        ...FORMATO_HORA,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    });
    const ESTADOS = { LIBRE: "Libre", OCUPADO: "Con tutoría confirmada" };
    // Errores que dicen que el bloque cambio desde que se cargo la lista.
    const CAMBIOS_DE_ESTADO = ["bloque_con_solicitudes", "bloque_con_reserva_confirmada"];
    const SIN_CONEXION =
        "No hay conexión con el servicio de Tutorías. Revisa que el sistema esté levantado.";

    // Id del bloque que se esta editando, o null si el formulario publica uno nuevo.
    let bloqueEnEdicion = null;

    document.addEventListener("DOMContentLoaded", iniciar);

    function porId(id) {
        return document.getElementById(id);
    }

    async function iniciar() {
        porId("formBloque").addEventListener("submit", guardar);
        porId("botonCancelar").addEventListener("click", salirDeEdicion);
        porId("fecha").min = partesDeChile(new Date()).fecha;

        let usuario = null;
        try {
            usuario = await Sesion.yo();
        } catch {
            porId("cargando").classList.add("hidden");
            mostrarAviso("error", "No hay conexión con el servicio de Identidad.");
            return;
        }
        porId("cargando").classList.add("hidden");
        if (!usuario) {
            mostrarSinSesion();
            return;
        }
        porId("conSesion").classList.remove("hidden");
        await cargarBloques();
    }

    // fetch a Tutorias con el token de acceso. Si vencio (dura 30 minutos), se
    // renueva una vez con la cookie y se reintenta, como en perfil.js.
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

    async function cargarBloques() {
        let r;
        try {
            r = await pedirTutorias("/disponibilidad");
        } catch {
            mostrarAviso("error", SIN_CONEXION);
            return;
        }
        if (r.estado === 401) {
            mostrarSinSesion("Tu sesión venció. Vuelve a iniciar sesión para ver tus bloques.");
            return;
        }
        if (!r.ok) {
            mostrarAviso("error", mensajeDeError(r.cuerpo, "No se pudieron cargar tus bloques."));
            return;
        }
        dibujarLista(Array.isArray(r.cuerpo) ? r.cuerpo : []);
    }

    async function guardar(evento) {
        evento.preventDefault();
        const fecha = porId("fecha").value;
        // Lo que se escribe es hora de Chile, este donde este el computador.
        const inicio = instanteDeChile(fecha, porId("horaInicio").value);
        const fin = instanteDeChile(fecha, porId("horaFin").value);
        if (Number.isNaN(inicio.getTime()) || Number.isNaN(fin.getTime())) {
            mostrarAviso("error", "Completa la fecha y las dos horas.");
            return;
        }
        const cuerpo = JSON.stringify({
            inicio_en: inicio.toISOString(),
            fin_en: fin.toISOString(),
        });
        const editando = bloqueEnEdicion;
        const boton = porId("botonGuardar");
        boton.disabled = true;
        try {
            const r = editando
                ? await pedirTutorias(`/disponibilidad/${encodeURIComponent(editando)}`, {
                      method: "PATCH",
                      body: cuerpo,
                  })
                : await pedirTutorias("/disponibilidad", { method: "POST", body: cuerpo });
            if (r.ok) {
                salirDeEdicion();
                mostrarAviso(
                    "exito",
                    editando ? "Bloque actualizado." : "Bloque publicado: los estudiantes ya lo pueden ver."
                );
                await cargarBloques();
            } else if (r.estado === 401) {
                mostrarSinSesion("Tu sesión venció. Vuelve a iniciar sesión para guardar el bloque.");
            } else if (r.cuerpo?.codigo === "no_es_tutor") {
                mostrarNoEsTutor();
            } else {
                mostrarAviso("error", mensajeDeError(r.cuerpo, "No se pudo guardar el bloque."));
                if (r.estado === 404 || CAMBIOS_DE_ESTADO.includes(r.cuerpo?.codigo)) {
                    salirDeEdicion();
                    await cargarBloques();
                }
            }
        } catch {
            mostrarAviso("error", SIN_CONEXION);
        } finally {
            boton.disabled = false;
        }
    }

    function editar(bloque) {
        const inicio = partesDeChile(new Date(bloque.inicio_en));
        porId("fecha").value = inicio.fecha;
        porId("horaInicio").value = inicio.hora;
        porId("horaFin").value = partesDeChile(new Date(bloque.fin_en)).hora;
        bloqueEnEdicion = bloque.id;
        porId("tituloFormulario").textContent = "Editar el bloque";
        porId("botonGuardar").textContent = "Guardar cambios";
        porId("botonCancelar").classList.remove("hidden");
        ocultarAviso();
        porId("formBloque").scrollIntoView({ behavior: "smooth", block: "start" });
        porId("fecha").focus({ preventScroll: true });
    }

    function salirDeEdicion() {
        bloqueEnEdicion = null;
        porId("formBloque").reset();
        porId("tituloFormulario").textContent = "Publicar un bloque";
        porId("botonGuardar").textContent = "Publicar bloque";
        porId("botonCancelar").classList.add("hidden");
    }

    async function eliminar(bloque) {
        const pendientes = bloque.solicitudes_pendientes;
        let pregunta = `¿Eliminar el bloque del ${describir(bloque)}?`;
        if (pendientes === 1) {
            pregunta += "\n\nTiene 1 solicitud pendiente: si lo eliminas, quedará rechazada.";
        } else if (pendientes > 1) {
            pregunta += `\n\nTiene ${pendientes} solicitudes pendientes: si lo eliminas, quedarán rechazadas.`;
        }
        if (!window.confirm(pregunta)) {
            return;
        }
        try {
            const r = await pedirTutorias(`/disponibilidad/${encodeURIComponent(bloque.id)}`, {
                method: "DELETE",
            });
            if (r.ok) {
                if (bloqueEnEdicion === bloque.id) {
                    salirDeEdicion();
                }
                mostrarAviso(
                    "exito",
                    pendientes > 0
                        ? "Bloque eliminado. Sus solicitudes pendientes quedaron rechazadas."
                        : "Bloque eliminado."
                );
                await cargarBloques();
            } else if (r.estado === 401) {
                mostrarSinSesion("Tu sesión venció. Vuelve a iniciar sesión para eliminar el bloque.");
            } else {
                mostrarAviso("error", mensajeDeError(r.cuerpo, "No se pudo eliminar el bloque."));
                await cargarBloques();
            }
        } catch {
            mostrarAviso("error", SIN_CONEXION);
        }
    }

    // ------------------------------------------------------------ dibujo

    function dibujarLista(bloques) {
        porId("listaBloques").replaceChildren(...bloques.map(itemDeBloque));
        porId("contadorBloques").textContent =
            bloques.length === 1 ? "1 bloque" : `${bloques.length} bloques`;
        porId("sinBloques").classList.toggle("hidden", bloques.length > 0);
    }

    function itemDeBloque(bloque) {
        const ocupado = bloque.estado === "OCUPADO";
        const pendientes = bloque.solicitudes_pendientes;
        const item = elemento("li", ocupado ? "disp-bloque disp-bloque-ocupado" : "disp-bloque");

        const cuando = elemento("div", "disp-bloque-cuando");
        cuando.append(
            elemento("strong", "disp-bloque-fecha", fechaDeChile(bloque.inicio_en)),
            elemento("span", "disp-bloque-horas", horario(bloque))
        );
        const estado = elemento(
            "span",
            ocupado ? "disp-estado disp-estado-ocupado" : "disp-estado",
            ESTADOS[bloque.estado] || bloque.estado
        );
        const cabecera = elemento("div", "disp-bloque-cabecera");
        cabecera.append(cuando, estado);
        item.appendChild(cabecera);

        if (pendientes > 0) {
            item.appendChild(
                elemento(
                    "p",
                    "disp-bloque-pendientes",
                    pendientes === 1 ? "1 solicitud pendiente" : `${pendientes} solicitudes pendientes`
                )
            );
        }

        if (ocupado) {
            item.appendChild(
                elemento(
                    "p",
                    "disp-bloque-nota",
                    "Tiene una tutoría confirmada: no se puede editar ni eliminar."
                )
            );
            return item;
        }
        if (pendientes > 0) {
            item.appendChild(
                elemento(
                    "p",
                    "disp-bloque-nota",
                    "Con solicitudes pendientes no se puede editar. Si lo eliminas, quedan rechazadas."
                )
            );
        }

        const acciones = elemento("div", "disp-bloque-acciones");
        if (pendientes === 0) {
            acciones.appendChild(
                boton("Editar", "fa-solid fa-pen", "disp-boton", `Editar el bloque del ${describir(bloque)}`, () =>
                    editar(bloque)
                )
            );
        }
        acciones.appendChild(
            boton(
                "Eliminar",
                "fa-solid fa-trash-can",
                "disp-boton disp-boton-peligro",
                `Eliminar el bloque del ${describir(bloque)}`,
                () => eliminar(bloque)
            )
        );
        item.appendChild(acciones);
        return item;
    }

    function mostrarAviso(tipo, texto) {
        const caja = porId("aviso");
        caja.className = `disp-aviso disp-aviso-${tipo}`;
        caja.textContent = texto;
        caja.scrollIntoView({ block: "nearest" });
    }

    function ocultarAviso() {
        const caja = porId("aviso");
        caja.className = "disp-aviso hidden";
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

    // 403 no_es_tutor: sin un perfil de tutor activo no se publica (HU-14).
    function mostrarNoEsTutor() {
        salirDeEdicion();
        porId("formBloque").classList.add("hidden");
        porId("noEsTutor").classList.remove("hidden");
        ocultarAviso();
    }

    // ------------------------------------------------------------ ayudas

    function elemento(etiqueta, clase, texto) {
        const nodo = document.createElement(etiqueta);
        if (clase) nodo.className = clase;
        if (texto !== undefined) nodo.textContent = texto;
        return nodo;
    }

    function boton(texto, icono, clase, etiqueta, alHacerClic) {
        const nodo = elemento("button", clase);
        nodo.type = "button";
        nodo.setAttribute("aria-label", etiqueta);
        const simbolo = elemento("i", icono);
        simbolo.setAttribute("aria-hidden", "true");
        nodo.append(simbolo, ` ${texto}`);
        nodo.addEventListener("click", alHacerClic);
        return nodo;
    }

    function fechaDeChile(iso) {
        return new Date(iso).toLocaleString("es-CL", FORMATO_FECHA);
    }

    function horaDeChile(iso) {
        return new Date(iso).toLocaleString("es-CL", FORMATO_HORA);
    }

    // "18:00 – 19:00", y la fecha del término si es otro día.
    function horario(bloque) {
        const horas = `${horaDeChile(bloque.inicio_en)} – ${horaDeChile(bloque.fin_en)}`;
        const otroDia = fechaDeChile(bloque.fin_en) !== fechaDeChile(bloque.inicio_en);
        return otroDia ? `${horas} (termina el ${fechaDeChile(bloque.fin_en)})` : horas;
    }

    // "jueves, 22 de octubre de 2026, de 18:00 a 19:00", para confirmar y para
    // el nombre accesible de los botones.
    function describir(bloque) {
        return `${fechaDeChile(bloque.inicio_en)}, de ${horaDeChile(bloque.inicio_en)} a ${horaDeChile(bloque.fin_en)}`;
    }

    // Fecha y hora de Chile de un instante, para los campos date y time.
    function partesDeChile(instante) {
        const p = {};
        for (const { type, value } of PARTES_DE_CHILE.formatToParts(instante)) {
            p[type] = value;
        }
        return { fecha: `${p.year}-${p.month}-${p.day}`, hora: `${p.hour}:${p.minute}` };
    }

    // El instante de una fecha y una hora de Chile, sin bibliotecas: se leen
    // como si fueran UTC y se corrige con el desfase que tiene Chile en ese
    // momento. La segunda vuelta es para los dias en que Chile cambia la hora;
    // una hora que ese dia no existe (al adelantar el reloj) queda una despues.
    function instanteDeChile(fecha, hora) {
        const buscado = Date.parse(`${fecha}T${hora}Z`);
        if (Number.isNaN(buscado)) {
            return new Date(NaN);
        }
        const desfase = (ms) => {
            const enChile = partesDeChile(new Date(ms));
            return Date.parse(`${enChile.fecha}T${enChile.hora}Z`) - ms;
        };
        const primero = buscado - desfase(buscado);
        const segundo = buscado - desfase(primero);
        return new Date(desfase(segundo) === desfase(primero) ? segundo : primero);
    }
})();
