document.addEventListener("DOMContentLoaded", () => {

    console.log("Plataforma Tutorías Duoc UC iniciada");

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


    alert(
        `Próximamente buscaremos tutores de: ${asignatura}`
    );

}