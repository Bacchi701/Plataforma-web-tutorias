# Sistema visual del frontend

Lo que ya usan las páginas de `frontend/` (HU-35, SCRUM-49). No agrega colores, letras ni componentes: los describe y dice en qué archivo están. Una página nueva usa esto; si necesita algo distinto, se agrega aquí.

## Colores, sombras, radio y letra

En `frontend/css/styles.css`, en `:root`. Se usan con `var(--nombre)`, sin repetir el valor a mano. El blanco todavía va como `white` en varias reglas, por ejemplo en la letra de `.btn-primary`: es el mismo valor que `--white`.

| Variable | Valor | Dónde se usa |
|---|---|---|
| `--duoc-blue` | `#003057` | Títulos, botón principal, enlaces de la cuenta |
| `--duoc-blue-light` | `#307FE2` | Etiquetas como «MI CUENTA», enlaces, foco de los campos |
| `--duoc-yellow` | `#FDBD2D` | Marca, botones de búsqueda, estrellas |
| `--duoc-yellow-hover` | `#eaae20` | Botones amarillos al pasar el mouse |
| `--dark` | `#111827` | Texto de la página (`body`) y de los campos |
| `--text` | `#374151` | Enlaces del encabezado, textos y etiquetas de los formularios |
| `--text-light` | `#6B7280` | Texto secundario y ayudas de los campos |
| `--background` | `#F7F8FA` | Fondo de las páginas con tarjetas |
| `--white` | `#FFFFFF` | Fondo de la página (`body`), de las tarjetas y de los botones con borde |
| `--border` | `#E5E7EB` | Bordes de tarjetas y de botones con borde |
| `--success` | `#16A34A` | El borde izquierdo verde de algunas tarjetas de lista (por ejemplo, un bloque ocupado o una reserva confirmada) |
| `--shadow` | `0 10px 30px rgba(0, 0, 0, .08)` | Tarjetas y buscadores |
| `--shadow-large` | `0 25px 60px rgba(0, 48, 87, .15)` | La tarjeta grande del inicio |
| `--radius` | `16px` | Tarjetas |

- **Letra:** `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`, en `body`. Ninguna página carga una letra propia: si el computador no tiene Inter, en Windows se ve Segoe UI y en macOS la del sistema. Los botones, los campos y los selectores heredan la familia (`font-family: inherit`).
- **Ancho de la página:** `.container`, `min(1180px, 90%)`.
- **Contraste:** `--duoc-blue-light` sobre blanco queda en 4:1, bajo el 4,5:1 que pide WCAG AA para el texto chico (las etiquetas como «MI CUENTA» y algunos enlaces). Es un color de la marca y cambiarlo cambia todas las páginas: HU-35 no lo cambió.

## Botones

| Botón | Clase | Archivo |
|---|---|---|
| Principal (fondo azul, letra blanca) | `.btn-primary`. En Mis reservas, pago y el panel va con `.res-boton-principal` o `.adm-boton-principal`, que solo le cambian el relleno y el alto | `styles.css`; `reservas.css` y `admin.css` |
| Principal a lo ancho de un formulario | `.profile-button` (Mi perfil); `.login-button` (inicio de sesión y verificación); `.register-button` (registro) | `perfil.css`; el `<style>` de `login.html`, `verificar.html` y `registro.html` |
| Secundario del encabezado (sin fondo, letra azul) | `.btn-login` | `styles.css` |
| Secundario con borde (fondo blanco, borde gris, letra azul) | `.disp-boton`, `.mis-asig-boton`, `.res-boton`, `.hist-boton`, `.adm-boton` | `disponibilidad.css`, `perfil.css`, `reservas.css`, `historial.css`, `admin.css` |
| Acción peligrosa (letra roja `#B91C1C`; al pasar el mouse, fondo `#FEF2F2` y borde `#FECACA`) | `.disp-boton-peligro`, `.mis-asig-boton-peligro`, `.res-boton-peligro`, `.adm-boton-peligro`, junto con la clase del botón con borde | los mismos |
| Búsqueda (amarillo) | `.btn-search` (inicio), `.subjects-search-button` (Asignaturas y Tutores) | `styles.css` |

- **Mientras espera la respuesta,** el botón queda deshabilitado. Se ve apagado (`opacity: .6`, y `.5` en el panel) en Mi perfil, Mi disponibilidad, el perfil del tutor, Mis reservas, pago, historial y el panel; en inicio de sesión y registro no hay ese estilo y se ve igual.
- **Las confirmaciones:** en Mis reservas, «Rechazar», «Retirar solicitud» y «Cancelar tutoría» piden una segunda pulsación del mismo botón, que mientras espera cambia su texto (por ejemplo, «¿Retirar? Pulsa de nuevo») y lleva `.res-boton-armado`. En Mi disponibilidad, «Eliminar» un bloque, y en el panel, «Desactivar» o «Activar» una cuenta y «Retirar evaluación», piden confirmar en la ventana del navegador (`window.confirm`).

## Campos y etiquetas de un formulario

La etiqueta va arriba (13 o 14 px, en negrita o seminegrita, `var(--text)`) y el campo debajo: de 48 a 52 px de alto, borde gris claro, radio de 10 px, fondo blanco o casi blanco y, con el foco, borde `var(--duoc-blue-light)`. La ayuda va debajo, en `var(--text-light)`.

| Página | Clases | Archivo |
|---|---|---|
| Inicio de sesión y registro | `.form-label`, `.input-container`, `.password-help` (solo en registro) | el `<style>` de `login.html` y `registro.html` |
| Mi perfil y Asignaturas que enseño | `.profile-label`, `.profile-input`, `.profile-hint` | `perfil.css` |
| Mi disponibilidad | `.disp-campo` | `disponibilidad.css` |
| Solicitud en el perfil del tutor | `.perfil-campo`, `.perfil-campo-ayuda` | `tutores.css` |
| Confirmar (Mis reservas), evaluación (historial) y panel | `.res-campo`, `.hist-campo`, `.adm-campo` (en el panel, la ayuda es `.adm-ayuda`) | `reservas.css`, `historial.css`, `admin.css` |
| Buscadores de Asignaturas y Tutores | `.subjects-search-input`, `.subjects-search-select` | `styles.css` |

El `<style>` de `verificar.html` trae las mismas reglas de campos que el de `login.html`, pero la página no tiene campos.

## Avisos de error y de éxito

- **En un formulario:** `avisar(caja, tipo, texto)`, de `js/sesion.js`, pinta la caja con `login-message` o `register-message` y `error` o `success`. Cada página que lo usa tiene esos estilos: inicio de sesión y verificación (`.login-message`, en su `<style>`), registro (`.register-message`, en su `<style>`), Mi perfil (`perfil.css`) y el perfil del tutor (`tutores.css`).
- **En la página:** Mi disponibilidad, Mis reservas, pago, historial y el panel muestran el aviso arriba, con una función propia: `.disp-aviso`, `.res-aviso` (también en `pago.html`), `.hist-aviso` y `.adm-aviso`, con `-error` o `-exito`. Pago usa además `.res-aviso-advertencia`, de `reservas.css`.
- **Colores:** error, fondo `#FEF2F2`, borde `#FECACA` y letra `#B91C1C`; éxito, fondo `#F0FDF4`, borde `#BBF7D0` y letra `#15803D`; advertencia, fondo `#FFFBEB`, borde `#FDE68A` y letra `#92400E`.
- Salvo en inicio de sesión, registro y verificación, el aviso va con `role="status"` y `aria-live="polite"`, y la página lo lleva a la vista con `scrollIntoView`.

## Tarjetas, siglas y estados

- **Tarjeta:** fondo blanco, borde `var(--border)`, radio `var(--radius)` y 24 px de relleno (18 y 16 px en pantallas de 420 px o menos): `.disp-tarjeta`, `.res-tarjeta`, `.hist-tarjeta` y `.adm-tarjeta`, en el CSS de cada página. Con otras medidas: `.profile-card` (Mi perfil, `perfil.css`: 32 px de relleno y sombra `var(--shadow)`), `.tutor-list-card` (Tutores, `styles.css`: 25 px) y `.subject-card` (Asignaturas, `styles.css`: radio de 20 px).
- **Sigla de una asignatura:** etiqueta con fondo `#EEF2F6`, letra `var(--duoc-blue)`, 12 px en negrita: `.res-sigla` (`reservas.css`), `.hist-sigla` (`historial.css`), `.adm-sigla` (`admin.css`) y `.subject-code` (`asignaturas.css`). En Mi perfil, `.mis-asig-sigla` (`perfil.css`), con fondo azul claro.
- **Estado:** píldora de 12 px en negrita (`border-radius: 999px`), con el color de cada estado: `.disp-estado`, `.mis-asig-estado`, `.res-estado`, `.hist-estado` y `.adm-estado`, en el CSS de cada página.

## Tablas

Ninguna página usa tablas: las listas van en tarjetas.

## El encabezado y el pie

- **Encabezado:** `.header`, fijo arriba, de 78 px, con la marca (`.brand`), los enlaces (`.nav-menu`) y los de la cuenta (`.nav-actions`, que `mostrarSesionEnEncabezado` de `sesion.js` cambia cuando hay sesión). En `styles.css`. Está en todas las páginas menos privacidad y términos.
- **Menú ☰:** `.mobile-menu`. Hasta 1439 px, los enlaces se esconden y el ☰ los muestra en columna (`.header.menu-abierto`, que pone `activarMenuMovil` de `sesion.js`; se cierra con Escape o al elegir un enlace). Desde 1440 px, el encabezado llega hasta 1300 px de ancho y va en una línea, salvo el del administrador: `sesion.js` le pone `.con-administracion` y usa el ☰ en todos los anchos.
- **Pie:** `footer`, fondo `#071d2f`, en `styles.css`. Está en diez páginas: todas menos inicio de sesión, registro, verificación, privacidad y términos. En la marca (`.footer-brand`), «Duoc UC» va en blanco y «Tutorías», en blanco al 60 %; los enlaces, en blanco al 60 %, y la descripción y el «© 2026…», al 55 %.

## Reglas

- **360 px sin desplazamiento horizontal.** El contenido cabe en unos 324 px (`.container` es el 90 %). Nada de anchos fijos mayores, ni filas que no bajen de línea (`flex-wrap: wrap`), ni columnas de grilla que no se encojan (`minmax(0, 1fr)`).
- **Los cortes:** en `styles.css`, 1439 px (☰) y 1440 px (encabezado de hasta 1300 px), 950 px (grillas del inicio y pie en dos columnas), 768 px (buscadores en columna) y 600 px (teléfono: pie en una columna). El `<style>` de registro y `perfil.css`, `reservas.css`, `historial.css`, `admin.css` y `tutores.css` también cambian en 600 px. Algunas páginas tienen los suyos: 1100 px (panel), 950 px (registro, en una columna), 900 px (Mi disponibilidad, perfil del tutor, inicio de sesión y verificación), 500 px (inicio de sesión y verificación) y 420 px (Mi disponibilidad, Mis reservas, historial y panel).
- **Un error dice qué corregir:** se muestra el mensaje de la API con `mensajeDeError(cuerpo, porDefecto)`, de `sesion.js` (primero los detalles por campo, después el mensaje), o uno propio que dice qué hacer. Nunca solo «Error».
- **Fechas y horas en hora de Chile:** llegan en UTC y se muestran con `toLocaleString("es-CL", …)` o `Intl.DateTimeFormat`, con `timeZone: "America/Santiago"` (la constante `ZONA_CHILE` de cada página).
- **Los datos, con `textContent` y `createElement`, nunca con `innerHTML`.**
- **Un texto largo sin espacios** (un enlace en `lugar_o_enlace`, una descripción) se corta con `overflow-wrap: anywhere`.

## Cómo revisar una página en 360 px

En el navegador, herramientas de desarrollador (F12) y el modo de dispositivo (Ctrl+Mayús+M), con un ancho de 360. Pega esto en la consola (la primera vez, el navegador pide escribir una frase para dejar pegar). La primera línea dice si hay desplazamiento horizontal, y la lista, qué elementos se salen:

```javascript
(() => {
    const ancho = document.documentElement.clientWidth;
    const fuera = [...document.querySelectorAll("body *")].filter(
        (e) => e.getBoundingClientRect().right > ancho + 1,
    );
    console.log(
        document.documentElement.scrollWidth > ancho
            ? "HAY desplazamiento horizontal. Elementos que se salen:"
            : "Sin desplazamiento horizontal.",
        fuera,
    );
})();
```

La lista puede traer adornos que su contenedor recorta (en el inicio, `div.visual-circle.circle-two`): lo que decide es la primera frase.
