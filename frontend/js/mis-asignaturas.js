// Seccion "Asignaturas que enseño" de Mi perfil (HU-14) y copia del nombre en
// Tutorias (HU-41), con la API real, por el gateway:
//   GET   /api/catalog/v1/carreras/{id}/asignaturas -> la malla vigente, por semestre
//   GET   /api/tutoring/v1/perfiles?usuario={id}    -> las que declaro el usuario
//   POST  /api/tutoring/v1/perfiles                 -> declara una
//   PATCH /api/tutoring/v1/perfiles/{id}            -> cambia la tarifa, la activa o la desactiva
//   POST  /api/tutoring/v1/yo/refrescar             -> al abrir y al guardar el perfil (HU-41)
// La pagina ofrece solo las asignaturas de los semestres anteriores al nivel
// (RN-01). Tutorias lo valida igual: la pagina solo ayuda.
// Las peticiones a Tutorias llevan el token de acceso. Si vencio, se renueva
// una vez con Sesion.renovar(), que se comparte con el resto de la pagina, y
// se reintenta, como en disponibilidad.js.
// Todo va dentro de una funcion: perfil.js ya declara CATALOGO, NIVEL_MAXIMO,
// opcion y otros nombres globales, y las paginas cargan scripts clasicos.
// Los datos se escriben con textContent y createElement, nunca con innerHTML.

(() => {
    "use strict";

    const RUTA_CATALOGO = "/api/catalog/v1";
    const RUTA_TUTORIAS = "/api/tutoring/v1";
    // perfil_tutor.tarifa es numeric(8, 0).
    const TARIFA_MAXIMA = 99999999;
    const TARIFA_INVALIDA =
        "Escribe la tarifa en pesos, sin decimales, por ejemplo 5.000. Escribe 0 si la tutoría es gratuita.";
    const SIN_CONEXION =
        "No hay conexión con el servicio de Tutorías. Revisa que el sistema esté levantado.";

    let usuario = null; // lo que trae /yo: id, carrera_id y nivel
    let declaradas = []; // GET /perfiles del propio usuario
    // Cada carga lleva un numero: si llega la respuesta de una anterior, se descarta.
    let ultimaCarga = 0;
    const mallas = new Map(); // carrera_id -> promesa con los semestres de su malla

    document.addEventListener("DOMContentLoaded", iniciar);
    // perfil.js lo dispara cuando el perfil queda guardado en Identidad.
    document.addEventListener("perfil-guardado", alGuardarElPerfil);

    function porId(id) {
        return document.getElementById(id);
    }

    async function iniciar() {
        porId("formAsignatura").addEventListener("submit", declarar);
        let datos;
        try {
            datos = await Sesion.yo();
        } catch {
            return; // perfil.js ya avisa que no hay conexion con Identidad
        }
        if (datos) {
            // Si un guardado anterior no alcanzo a poner al dia la copia de
            // Tutorias, se pone al dia ahora (HU-41, criterio 3).
            refrescarCopia();
            await mostrar(datos);
        }
        // Sin sesion, perfil.js muestra el enlace para entrar.
    }

    // El nombre, la carrera o el nivel pueden haber cambiado: la copia de
    // Tutorias se pone al dia (HU-41) y la seccion se vuelve a armar.
    function alGuardarElPerfil(evento) {
        refrescarCopia();
        if (evento.detail) {
            mostrar(evento.detail);
        }
    }

    // HU-41: la busqueda y el perfil publico leen el nombre de la copia de
    // Tutorias. Si Tutorias no responde, el perfil igual quedo guardado en
    // Identidad y la copia se pone al dia la proxima vez que se abre o se
    // guarda Mi perfil (criterio 3): no se le avisa nada al usuario. Si el
    // usuario no tiene copia, Tutorias responde sin llamar a Identidad.
    async function refrescarCopia() {
        try {
            const r = await pedirTutorias("/yo/refrescar", { method: "POST" });
            if (!r.ok) {
                console.warn(`Tutorías respondió ${r.estado} al poner al día tu nombre.`);
            }
        } catch (error) {
            console.warn("Tutorías no respondió al poner al día tu nombre:", error);
        }
    }

    // fetch a Tutorias con el token de acceso. Si vencio (dura 30 minutos), se
    // renueva una vez y se reintenta.
    async function pedirTutorias(ruta, opciones = {}) {
        const enviar = () =>
            fetch(RUTA_TUTORIAS + ruta, {
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
        try {
            cuerpo = await respuesta.json();
        } catch {
            cuerpo = null;
        }
        return { ok: respuesta.ok, estado: respuesta.status, cuerpo };
    }

    // La malla vigente de la carrera, una vez por carrera. Es publica.
    function mallaDe(carreraId) {
        if (!mallas.has(carreraId)) {
            const url = `${RUTA_CATALOGO}/carreras/${encodeURIComponent(carreraId)}/asignaturas`;
            const promesa = fetch(url, { headers: { Accept: "application/json" } })
                .then((respuesta) => {
                    if (!respuesta.ok) {
                        throw new Error(`El catálogo respondió ${respuesta.status}`);
                    }
                    return respuesta.json();
                })
                .then((cuerpo) => (Array.isArray(cuerpo.semestres) ? cuerpo.semestres : []));
            // Si falla, la proxima carga lo vuelve a intentar.
            promesa.catch(() => mallas.delete(carreraId));
            mallas.set(carreraId, promesa);
        }
        return mallas.get(carreraId);
    }

    async function cargarDeclaradas() {
        try {
            const r = await pedirTutorias(`/perfiles?${new URLSearchParams({ usuario: usuario.id })}`);
            if (r.ok && Array.isArray(r.cuerpo)) {
                return r.cuerpo;
            }
            if (r.estado === 401) {
                avisarAqui("error", "Tu sesión terminó. Vuelve a iniciar sesión para ver tus asignaturas.");
            } else {
                avisarAqui("error", mensajeDeError(r.cuerpo, "No se pudieron cargar tus asignaturas."));
            }
        } catch {
            avisarAqui("error", SIN_CONEXION);
        }
        return null;
    }

    // Arma la seccion con lo que trae /yo (o lo que respondio el PATCH /yo).
    async function mostrar(datos) {
        usuario = datos;
        const numero = ++ultimaCarga;
        porId("misAsignaturas").classList.remove("hidden");

        const completo = Boolean(usuario.carrera_id && usuario.nivel);
        const [lista, semestres] = await Promise.all([
            cargarDeclaradas(),
            completo && usuario.nivel > 1
                ? mallaDe(usuario.carrera_id).catch(() => null)
                : Promise.resolve([]),
        ]);
        if (numero !== ultimaCarga) {
            return; // mientras tanto llego otra carga
        }
        if (lista) {
            declaradas = lista;
        }
        dibujarLista();
        dibujarFormulario(completo, semestres);
    }

    // ------------------------------------------------ formulario para declarar

    function dibujarFormulario(completo, semestres) {
        const formulario = porId("formAsignatura");
        let aviso = null;
        let grupos = [];
        if (!completo) {
            aviso = "Completa tu carrera y tu nivel para declarar asignaturas.";
        } else if (usuario.nivel === 1) {
            aviso =
                "Estás en el primer semestre: desde el segundo podrás ofrecer tutorías de las asignaturas que ya cursaste.";
        } else if (semestres === null) {
            aviso =
                "No pudimos cargar las asignaturas de tu carrera desde el catálogo. Recarga la página en unos minutos.";
        } else {
            grupos = opcionesPorSemestre(semestres);
            if (grupos.length === 0) {
                aviso = avisoSinOpciones(semestres);
            }
        }

        const caja = porId("avisoAsignaturas");
        caja.textContent = aviso || "";
        caja.classList.toggle("hidden", !aviso);
        formulario.classList.toggle("hidden", Boolean(aviso));

        const selector = porId("asignaturaNueva");
        selector.replaceChildren(nodo("option", null, "Elige una asignatura"));
        selector.firstChild.value = "";
        grupos.forEach(({ semestre, asignaturas }) => {
            const grupo = nodo("optgroup");
            grupo.label = `Semestre ${semestre}`;
            asignaturas.forEach((asignatura) => {
                const opcion = nodo("option", null, `${asignatura.sigla} · ${asignatura.nombre}`);
                opcion.value = asignatura.id;
                grupo.appendChild(opcion);
            });
            selector.appendChild(grupo);
        });
    }

    // Por que no hay nada que elegir, con la malla ya cargada.
    function avisoSinOpciones(semestres) {
        if (semestres.length === 0) {
            return "Tu carrera todavía no tiene una malla vigente en el catálogo.";
        }
        const hayAnteriores = semestres.some(
            (grupo) => grupo.semestre < usuario.nivel && (grupo.asignaturas || []).length > 0
        );
        return hayAnteriores
            ? "Ya declaraste todas las asignaturas que puedes enseñar."
            : "Tu malla no tiene asignaturas en los semestres anteriores al que cursas.";
    }

    // Las de los semestres anteriores al nivel (RN-01), sin las ya declaradas,
    // activas o no: las desactivadas se vuelven a activar desde la lista.
    function opcionesPorSemestre(semestres) {
        const yaDeclaradas = new Set(declaradas.map((perfil) => perfil.asignatura.asignatura_id));
        return semestres
            .filter((grupo) => grupo.semestre < usuario.nivel)
            .map((grupo) => ({
                semestre: grupo.semestre,
                asignaturas: (grupo.asignaturas || []).filter(
                    (asignatura) => !yaDeclaradas.has(asignatura.id)
                ),
            }))
            .filter((grupo) => grupo.asignaturas.length > 0);
    }

    async function declarar(evento) {
        evento.preventDefault();
        const asignaturaId = porId("asignaturaNueva").value;
        const tarifa = leerTarifa(porId("tarifaNueva").value);
        const descripcion = porId("descripcionNueva").value.trim();
        if (!asignaturaId) {
            porId("asignaturaNueva").focus({ preventScroll: true });
            avisarAqui("error", "Elige la asignatura que quieres enseñar.");
            return;
        }
        if (tarifa === null) {
            porId("tarifaNueva").focus({ preventScroll: true });
            avisarAqui("error", TARIFA_INVALIDA);
            return;
        }

        const botonDeclarar = porId("botonDeclarar");
        botonDeclarar.disabled = true;
        try {
            const r = await pedirTutorias("/perfiles", {
                method: "POST",
                body: JSON.stringify({
                    asignatura_id: asignaturaId,
                    tarifa,
                    descripcion: descripcion || null,
                }),
            });
            if (r.ok) {
                porId("formAsignatura").reset();
                avisarAqui(
                    "success",
                    `Agregaste ${r.cuerpo.asignatura.nombre}: ya apareces como tutor en la búsqueda.`
                );
                await mostrar(usuario);
            } else if (r.estado === 401) {
                avisarAqui("error", "Tu sesión terminó. Vuelve a iniciar sesión para declarar asignaturas.");
            } else {
                avisarAqui("error", mensajeDeError(r.cuerpo, "No se pudo agregar la asignatura."));
            }
        } catch {
            avisarAqui("error", SIN_CONEXION);
        } finally {
            botonDeclarar.disabled = false;
        }
    }

    // ------------------------------------------------ lista de las declaradas

    function dibujarLista() {
        const lista = porId("listaMisAsignaturas");
        lista.replaceChildren(...declaradas.map(itemDeLaLista));
        lista.classList.toggle("hidden", declaradas.length === 0);
        // Con una activa ya es tutor: el siguiente paso es publicar horarios (HU-15).
        porId("siguientePaso").classList.toggle(
            "hidden",
            !declaradas.some((perfil) => perfil.activo)
        );
    }

    function itemDeLaLista(perfil) {
        const { sigla, nombre } = perfil.asignatura;
        const item = nodo("li", perfil.activo ? "mis-asig-item" : "mis-asig-item mis-asig-inactiva");

        const cabecera = nodo("div", "mis-asig-cabecera");
        const titulo = nodo("div", "mis-asig-titulo");
        titulo.append(nodo("span", "mis-asig-sigla", sigla), nodo("strong", null, nombre));
        cabecera.append(
            titulo,
            nodo("span", "mis-asig-estado", perfil.activo ? "Activa" : "Desactivada")
        );
        item.appendChild(cabecera);

        const tarifa = nodo("p", "mis-asig-tarifa");
        tarifa.append(nodo("span", null, "Tarifa: "), nodo("strong", null, tarifaEnTexto(perfil.tarifa)));
        item.appendChild(tarifa);
        if (perfil.descripcion) {
            item.appendChild(nodo("p", "mis-asig-descripcion", perfil.descripcion));
        }

        const acciones = nodo("div", "mis-asig-acciones");
        const cambiar = boton("Cambiar tarifa", `Cambiar la tarifa de ${nombre}`);
        cambiar.dataset.perfil = perfil.id;
        cambiar.dataset.accion = "tarifa";
        const alternar = boton(
            perfil.activo ? "Desactivar" : "Activar",
            `${perfil.activo ? "Desactivar" : "Activar"} ${nombre}`
        );
        alternar.dataset.perfil = perfil.id;
        alternar.dataset.accion = "activo";
        if (perfil.activo) {
            alternar.classList.add("mis-asig-boton-peligro");
        }
        acciones.append(cambiar, alternar);
        item.appendChild(acciones);

        const edicion = formularioDeTarifa(perfil);
        item.appendChild(edicion);
        cambiar.setAttribute("aria-expanded", "false");
        cambiar.setAttribute("aria-controls", edicion.id);
        cambiar.addEventListener("click", () => {
            const abierta = edicion.classList.toggle("hidden") === false;
            cambiar.setAttribute("aria-expanded", String(abierta));
            if (abierta) {
                edicion.querySelector("input").focus();
            }
        });
        alternar.addEventListener("click", () =>
            guardarCambio(perfil, { activo: !perfil.activo }, alternar, "activo")
        );
        return item;
    }

    function formularioDeTarifa(perfil) {
        const formulario = nodo("form", "mis-asig-edicion hidden");
        formulario.id = `tarifa-${perfil.id}`;
        formulario.noValidate = true;
        const campo = nodo("input", "profile-input");
        campo.type = "text";
        campo.inputMode = "numeric";
        campo.autocomplete = "off";
        campo.maxLength = 11;
        campo.id = `tarifaDe-${perfil.id}`;
        campo.value = String(perfil.tarifa).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
        const etiqueta = nodo("label", "profile-label", `Tarifa nueva de ${perfil.asignatura.nombre}, en pesos`);
        etiqueta.htmlFor = campo.id;
        const guardar = nodo("button", "profile-button mis-asig-guardar", "Guardar tarifa");
        guardar.type = "submit";
        formulario.append(etiqueta, campo, guardar);
        formulario.addEventListener("submit", (evento) => {
            evento.preventDefault();
            const tarifa = leerTarifa(campo.value);
            if (tarifa === null) {
                campo.focus();
                avisarAqui("error", TARIFA_INVALIDA);
                return;
            }
            guardarCambio(perfil, { tarifa }, guardar, "tarifa");
        });
        return formulario;
    }

    // PATCH /perfiles/{id}. Reactivar puede responder 400 si RN-01 ya no la
    // habilita (el nivel o la carrera cambiaron): se muestra el mensaje.
    async function guardarCambio(perfil, cambios, botonUsado, accion) {
        botonUsado.disabled = true;
        try {
            const r = await pedirTutorias(`/perfiles/${encodeURIComponent(perfil.id)}`, {
                method: "PATCH",
                body: JSON.stringify(cambios),
            });
            if (r.ok) {
                declaradas = declaradas.map((otro) => (otro.id === r.cuerpo.id ? r.cuerpo : otro));
                dibujarLista();
                avisarAqui("success", textoDelCambio(r.cuerpo, cambios));
                enfocar(perfil.id, accion);
                return;
            }
            if (r.estado === 401) {
                avisarAqui("error", "Tu sesión terminó. Vuelve a iniciar sesión para cambiar tus asignaturas.");
            } else {
                avisarAqui("error", mensajeDeError(r.cuerpo, "No se pudo guardar el cambio."));
            }
        } catch {
            avisarAqui("error", SIN_CONEXION);
        }
        botonUsado.disabled = false;
    }

    function textoDelCambio(perfil, cambios) {
        const nombre = perfil.asignatura.nombre;
        if ("tarifa" in cambios) {
            return `La tarifa de ${nombre} quedó en ${tarifaEnTexto(perfil.tarifa)}.`;
        }
        return perfil.activo
            ? `${nombre} está activa otra vez: aparece en la búsqueda.`
            : `Desactivaste ${nombre}: ya no aparece en la búsqueda.`;
    }

    // Despues de rearmar la lista, el foco vuelve al boton equivalente.
    function enfocar(perfilId, accion) {
        const accionBoton = accion === "tarifa" ? "tarifa" : "activo";
        const destino = [...document.querySelectorAll("#listaMisAsignaturas button")].find(
            (b) => b.dataset.perfil === perfilId && b.dataset.accion === accionBoton
        );
        if (destino) {
            destino.focus({ preventScroll: true });
        }
    }

    // ------------------------------------------------ utilidades

    // "5000", "5.000" o "$5.000": un entero de pesos. El punto solo vale como
    // separador de miles ("5.5" no es una tarifa). Con otra cosa, null.
    function leerTarifa(texto) {
        const limpio = texto.trim().replace(/^\$\s*/, "");
        if (!/^(\d{1,3}(\.\d{3})+|\d+)$/.test(limpio)) {
            return null;
        }
        const monto = Number(limpio.replace(/\./g, ""));
        return monto <= TARIFA_MAXIMA ? monto : null;
    }

    // "Gratis" si es 0; si no, en pesos con el separador de miles chileno: $5.000.
    function tarifaEnTexto(tarifa) {
        const monto = Math.round(Number(tarifa));
        if (monto === 0) {
            return "Gratis";
        }
        return `$${String(monto).replace(/\B(?=(\d{3})+(?!\d))/g, ".")}`;
    }

    // Avisa con avisar() de sesion.js y lleva el aviso a la vista.
    function avisarAqui(tipo, texto) {
        const caja = porId("mensajeAsignaturas");
        avisar(caja, tipo, texto);
        caja.scrollIntoView({ block: "nearest" });
    }

    function nodo(etiqueta, clase, texto) {
        const elemento = document.createElement(etiqueta);
        if (clase) {
            elemento.className = clase;
        }
        if (texto !== undefined) {
            elemento.textContent = texto;
        }
        return elemento;
    }

    function boton(texto, etiquetaAccesible) {
        const elemento = nodo("button", "mis-asig-boton", texto);
        elemento.type = "button";
        elemento.setAttribute("aria-label", etiquetaAccesible);
        return elemento;
    }
})();
