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


    // Pasos de "Encuentra ayuda en pocos pasos". Con mouse, la tarjeta se
    // abre al pasar el mouse o al llegar con Tab (solo CSS) y el clic no
    // hace nada. En pantallas tactiles, un toque en la tarjeta (o Enter en
    // "Ver más") la deja abierta o la cierra.
    const conMouse =
        window.matchMedia("(hover: hover) and (pointer: fine)").matches;

    if (!conMouse) {

        document.querySelectorAll(".step-card").forEach((tarjeta) => {

            const boton = tarjeta.querySelector(".step-toggle");

            if (!boton) {
                return;
            }

            tarjeta.addEventListener("click", () => {

                const abierta = tarjeta.classList.toggle("abierta");

                boton.setAttribute("aria-expanded", String(abierta));
                boton.querySelector("span").textContent = abierta ? "Ver menos" : "Ver más";

            });

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


// Abre la busqueda de tutores con el texto ya buscado (HU-18).
function irABusqueda(texto) {

    window.location.href =
        `tutores.html?buscar=${encodeURIComponent(texto)}`;

}