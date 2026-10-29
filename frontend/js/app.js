document.addEventListener("DOMContentLoaded", () => {

    console.log("Plataforma Tutorías Duoc UC iniciada");


    // Enter en el buscador de la portada hace lo mismo que el boton
    // "Buscar tutor". Va en keydown: con keyup, el Enter que cierra el aviso
    // de la caja vacia llegaria despues a la caja y volveria a abrirlo.
    const buscador =
        document.getElementById("searchInput");

    if (buscador) {

        buscador.addEventListener("keydown", (evento) => {

            if (evento.key === "Enter" && !evento.isComposing) {

                evento.preventDefault();

                buscarTutor();
            }

        });
    }


    // "Prueba con": cada asignatura abre la busqueda de tutores con su
    // nombre, o con data-buscar si el nombre del boton no coincide con el
    // del catalogo (el catalogo dice "Matematica", no "Matematicas").
    document
        .querySelectorAll(".popular-searches button")
        .forEach((boton) => {

            boton.addEventListener("click", () => {

                irABusqueda(
                    boton.dataset.buscar || boton.textContent.trim()
                );

            });

        });

});


function buscarTutor() {

    const input =
        document.getElementById("searchInput");

    const asignatura =
        input.value.trim();


    if (!asignatura) {

        alert(
            "Ingresa una asignatura para buscar tutores."
        );

        input.focus();

        return;
    }


    console.log(
        "Buscando tutores para:",
        asignatura
    );


    irABusqueda(asignatura);

}


// Abre Asignaturas con el texto ya buscado: ahi cada asignatura despliega
// sus tutores (HU-40). La busqueda por nombre del tutor esta en tutores.html.
function irABusqueda(texto) {

    window.location.href =
        `asignaturas.html?buscar=${encodeURIComponent(texto)}`;

}