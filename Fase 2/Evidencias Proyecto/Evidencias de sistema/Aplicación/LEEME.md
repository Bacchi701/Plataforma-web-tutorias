# Evidencias de sistema · Aplicación

Versión 1.0 · 03-11-2026 · datos al 02-11-2026

Dos videos de la plataforma funcionando en un computador, con el sistema
corriendo en local y abierto en el navegador: las páginas en `localhost:8080`
y la bandeja de correo de desarrollo en `localhost:8025`. Ninguno de los dos
tiene sonido.

Las cuentas que se ven son de los datos de ejemplo, como
`valentina.demo@duocuc.cl` o `camila.demo@duocuc.cl`, salvo la que se crea
durante la grabación para mostrar el registro: en los dos videos es
`bryan@duocuc.cl`, a nombre de Bryan Bacchi. Los correos llegan a la bandeja
de correo de desarrollo (Mailpit), no a una casilla real.

## `Demo_Plataforma_Tutorias_16-10.mp4`

- **Fecha:** 16-10-2026. Se grabó para mostrar el avance de la Fase 2 que el
  profesor quiso ver ese día.
- **Duración:** 3 min 44 s, sin sonido.
- **Versión:** la demo del 02-10 (rama `demo/semana-08`). Al 16-10, ese código
  todavía no estaba en `develop`.
- **Qué se ve:**
  1. La página para iniciar sesión y la portada.
  2. Una tutora de ejemplo (`valentina.demo@duocuc.cl`) inicia sesión y abre
     «Asignaturas»: el filtro por carrera y las búsquedas «base de» (encuentra
     dos), «progra» (tres) y «mate» (dos).
  3. Dos inicios de sesión rechazados: el de una cuenta sin verificar
     (`tomas.demo@duocuc.cl`: «Verifica tu correo antes de iniciar sesión:
     revisa tu bandeja») y el de una cuenta desactivada (`josefa.demo@duocuc.cl`:
     «Tu cuenta está desactivada»).
  4. El registro de una cuenta nueva (`bryan@duocuc.cl`, a nombre de Bryan
     Bacchi), el correo de verificación en la bandeja de desarrollo, el enlace
     que confirma el correo («Tu correo quedó verificado. Ya puedes iniciar
     sesión») y el inicio de sesión con esa cuenta.
- La portada de esa versión trae cifras y tarjetas de diseño que no salen de la
  base de datos, como «500+ Tutorías realizadas» y las tarjetas de «Tutores
  destacados»; una de ellas usa el nombre de Damaris Iriarte.

## `demo_30-10.mp4`

- **Fecha:** 30-10-2026. Es el video de respaldo de la sesión obligatoria con
  el profesor de ese día. Llegó al repositorio con la presentación de esa
  sesión, en el PR #26.
- **Duración:** 10 min 36 s, sin sonido.
- **Qué se ve:**
  1. La portada.
  2. El registro: un correo que no es @duocuc.cl (`bryan@gmail.com`) se rechaza
     («Usa tu correo institucional, que termina en @duocuc.cl»). Con
     `bryan@duocuc.cl`, a nombre de Bryan Bacchi, el correo de verificación
     llega a la bandeja de desarrollo, y después se inicia sesión.
  3. «Mi perfil»: el aviso de perfil incompleto, la elección de carrera, sede y
     nivel, y el mensaje «Tu perfil quedó guardado». Con «Semestre 1»,
     «Asignaturas que enseño» avisa: «Estás en el primer semestre: desde el
     segundo podrás ofrecer tutorías de las asignaturas que ya cursaste».
  4. Una estudiante de segundo semestre (`camila.demo@duocuc.cl`), en
     «Asignaturas que enseño»: la lista solo le ofrece asignaturas del primer
     semestre. Declara «Base de Datos» gratis y «Matemática Aplicada» a $4.000,
     cambia esa tarifa a $3.500 («La tarifa de Matemática Aplicada quedó en
     $3.500»), desactiva «Base de Datos» («Desactivaste Base de Datos: ya no
     aparece en la búsqueda») y cambia su nombre a «Camila Andrea».
  5. «Mi disponibilidad»: publica un bloque de horario, otro bloque que se
     cruza con el primero se rechaza («El bloque se cruza con otro de tus
     bloques. Elige otro horario»), edita un bloque y elimina otro.
  6. «Asignaturas»: el filtro por carrera, la búsqueda «datos» y «Ver tutores»
     en cada asignatura. Después, en «Mi perfil», vuelve a activar «Base de
     Datos» («Base de Datos está activa otra vez: aparece en la búsqueda»).
  7. «Tutores»: los mejor evaluados, el filtro «4 estrellas o más», la búsqueda
     por nombre («cami»), que ya encuentra a la estudiante con su nombre nuevo,
     y los perfiles de Valentina Soto y de Camila Andrea Rojas. El botón
     «Solicitar tutoría» dice «Disponible pronto»: esa función llega con HU-21.
  8. En una pantalla de 360 px de ancho, como la de un teléfono: la búsqueda de
     tutores («cami») y el perfil de la tutora; «Mi perfil», donde declara
     «Ética para el Trabajo» a $2.000; «Mi disponibilidad», donde publica un
     bloque; «Asignaturas», con la búsqueda «Matemática», y la portada, con el
     menú ☰ y «Ver más» en sus pasos.
