// Pagina del enlace del correo: verificar.html?token=... (HU-04, criterio 3).

document.addEventListener("DOMContentLoaded", async () => {
    const aviso = document.getElementById("verifyMessage");
    const token = new URLSearchParams(window.location.search).get("token");

    if (!token) {
        avisar(aviso, "error", "El enlace no trae el código de verificación.");
        return;
    }
    try {
        const r = await Sesion.pedir("/verificar-correo", {
            method: "POST",
            body: JSON.stringify({ token }),
        });
        avisar(
            aviso,
            r.ok ? "success" : "error",
            r.ok ? r.cuerpo.mensaje : mensajeDeError(r.cuerpo, "No se pudo verificar el correo.")
        );
    } catch {
        avisar(aviso, "error", "No hay conexión con el servicio de Identidad.");
    }
});
