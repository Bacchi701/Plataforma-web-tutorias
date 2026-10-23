// Pantalla de inicio de sesion (HU-09) contra POST /api/identity/v1/login.

document.addEventListener("DOMContentLoaded", () => {
    const formulario = document.getElementById("loginForm");
    const aviso = document.getElementById("loginMessage");
    const clave = document.getElementById("password");
    const icono = document.getElementById("passwordIcon");

    document.getElementById("passwordToggle").addEventListener("click", () => {
        const oculta = clave.type === "password";
        clave.type = oculta ? "text" : "password";
        icono.className = oculta ? "fa-regular fa-eye-slash" : "fa-regular fa-eye";
    });

    formulario.addEventListener("submit", async (evento) => {
        evento.preventDefault();
        const email = document.getElementById("email").value.trim();
        const password = clave.value;

        if (!email || !password) {
            avisar(aviso, "error", "Ingresa tu correo y tu contraseña.");
            return;
        }

        const boton = formulario.querySelector('button[type="submit"]');
        boton.disabled = true;
        try {
            const r = await Sesion.entrar(email, password);
            if (r.ok) {
                avisar(aviso, "success", "Sesión iniciada. Entrando...");
                setTimeout(() => {
                    window.location.href = "index.html";
                }, 700);
                return;
            }
            avisar(aviso, "error", mensajeDeError(r.cuerpo, "No se pudo iniciar sesión."));
        } catch {
            avisar(aviso, "error", "No hay conexión con el servicio de Identidad.");
        } finally {
            boton.disabled = false;
        }
    });
});
