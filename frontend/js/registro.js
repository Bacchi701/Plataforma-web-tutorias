// Pantalla de registro (HU-09) contra POST /api/identity/v1/registro.
// Pide solo nombre, apellido, correo institucional y contrasena (criterio 1).

const DOMINIO = "@duocuc.cl";

// Lo usan los botones del ojo en registro.html (onclick).
function togglePassword(idCampo, idIcono) {
    const campo = document.getElementById(idCampo);
    const icono = document.getElementById(idIcono);
    const oculta = campo.type === "password";
    campo.type = oculta ? "text" : "password";
    icono.className = oculta ? "fa-regular fa-eye-slash" : "fa-regular fa-eye";
}

function problemaAntesDeEnviar(datos, confirmacion, aceptaTerminos) {
    if (!datos.nombre || !datos.apellido) {
        return "Completa tu nombre y tu apellido.";
    }
    if (!datos.email.toLowerCase().endsWith(DOMINIO)) {
        return "Usa tu correo institucional, que termina en @duocuc.cl.";
    }
    if (datos.password.length < 8) {
        return "La contraseña debe tener al menos 8 caracteres.";
    }
    if (datos.password !== confirmacion) {
        return "Las contraseñas no coinciden.";
    }
    if (!aceptaTerminos) {
        return "Debes aceptar los términos y la política de privacidad.";
    }
    return null;
}

document.addEventListener("DOMContentLoaded", () => {
    const formulario = document.getElementById("registerForm");
    const aviso = document.getElementById("registerMessage");

    formulario.addEventListener("submit", async (evento) => {
        evento.preventDefault();
        const datos = {
            nombre: document.getElementById("nombre").value.trim(),
            apellido: document.getElementById("apellido").value.trim(),
            email: document.getElementById("email").value.trim(),
            password: document.getElementById("password").value,
        };
        const problema = problemaAntesDeEnviar(
            datos,
            document.getElementById("confirmPassword").value,
            document.getElementById("terms").checked
        );
        if (problema) {
            avisar(aviso, "error", problema);
            return;
        }

        const boton = formulario.querySelector('button[type="submit"]');
        boton.disabled = true;
        try {
            const r = await Sesion.pedir("/registro", {
                method: "POST",
                body: JSON.stringify(datos),
            });
            if (r.ok) {
                formulario.reset();
                avisar(
                    aviso,
                    r.cuerpo.correo_enviado ? "success" : "error",
                    r.cuerpo.correo_enviado
                        ? `Te enviamos un correo a ${r.cuerpo.email}. Ábrelo y sigue el enlace para verificar tu cuenta.`
                        : "Tu cuenta quedó creada, pero no se pudo enviar el correo de verificación. Inténtalo más tarde."
                );
                return;
            }
            avisar(aviso, "error", mensajeDeError(r.cuerpo, "No se pudo crear la cuenta."));
        } catch {
            avisar(aviso, "error", "No hay conexión con el servicio de Identidad.");
        } finally {
            boton.disabled = false;
        }
    });
});
