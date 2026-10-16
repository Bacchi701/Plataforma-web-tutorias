-- Datos FICTICIOS de ejemplo para identity_db (demostracion, semana 8).
-- Ninguna persona es real: los correos son inventados (nombre.demo@duocuc.cl)
-- y la clave de todas las cuentas es Tutorias2026.
-- Los identificadores son los mismos en las cuatro bases, para que se pueda
-- seguir una reserva de una base a otra.
-- Se puede ejecutar las veces que haga falta: vacia sus tablas y las llena.
-- Uso: .\scripts\cargar_datos_demo.ps1  (o los dos comandos del RUNBOOK).

\set ON_ERROR_STOP on
BEGIN;

TRUNCATE aviso_correo, refresh_token, token_verificacion, usuario RESTART IDENTITY CASCADE;

-- 8 cuentas: 3 tutores, 2 estudiantes, 1 desactivada, 1 sin verificar y 1 administrador.
INSERT INTO usuario (id, email, password_hash, nombre, apellido, carrera_id, nivel, sede_id, email_verificado, activo, es_admin, creado_en, actualizado_en) VALUES
    ('10000000-0000-4000-8000-000000000001', 'valentina.demo@duocuc.cl', 'pbkdf2_sha256$1000000$DHFVSsuPss05MktqvbFNYB$gL1OvDnpy8cW+T+4wby/V5Z68IkPJLJJeP53LP/Ik/Y=', 'Valentina', 'Soto', '20000000-0000-4000-8000-000000000001', 6, '30000000-0000-4000-8000-000000000011', true, true, false, '2026-09-10 13:00:00+00', '2026-09-10 13:00:00+00'),
    ('10000000-0000-4000-8000-000000000002', 'matias.demo@duocuc.cl', 'pbkdf2_sha256$1000000$dznZam1J0T74cwXDfNGUlq$PGqjJDhlGC6mYRkQb6R6/Laon5PgTVWI36pa84Ia1xg=', 'Matías', 'Fuentes', '20000000-0000-4000-8000-000000000002', 4, '30000000-0000-4000-8000-000000000004', true, true, false, '2026-09-10 14:30:00+00', '2026-09-10 14:30:00+00'),
    ('10000000-0000-4000-8000-000000000003', 'fernanda.demo@duocuc.cl', 'pbkdf2_sha256$1000000$JvJ61UWaz3zZPdIKIAiioI$lwtvpYx2KiWQPTQbVrehS67oGe75huQqY9NTJZAhEtY=', 'Fernanda', 'Castro', '20000000-0000-4000-8000-000000000001', 7, '30000000-0000-4000-8000-000000000001', true, true, false, '2026-09-11 12:15:00+00', '2026-09-11 12:15:00+00'),
    ('10000000-0000-4000-8000-000000000004', 'camila.demo@duocuc.cl', 'pbkdf2_sha256$1000000$JF8To41iUViCFscqLfKgQL$3tQcxLbzgNCCo+Uwvg+gCuvN+NbnlhPYjF6Ch2vwdnQ=', 'Camila', 'Rojas', '20000000-0000-4000-8000-000000000001', 2, '30000000-0000-4000-8000-000000000011', true, true, false, '2026-09-12 16:40:00+00', '2026-09-12 16:40:00+00'),
    ('10000000-0000-4000-8000-000000000005', 'diego.demo@duocuc.cl', 'pbkdf2_sha256$1000000$Z52LZxfAAU2bg8kp8USoFz$oL9lIEIQvuNve722Gxr5N1FnzlpnYqzDJzCKD1X4TUM=', 'Diego', 'Herrera', '20000000-0000-4000-8000-000000000002', 1, '30000000-0000-4000-8000-000000000004', true, true, false, '2026-09-13 18:05:00+00', '2026-09-13 18:05:00+00'),
    ('10000000-0000-4000-8000-000000000006', 'josefa.demo@duocuc.cl', 'pbkdf2_sha256$1000000$7Otpx103TM7pc9Fn65qDQP$7jFUZ7ejAlGgSPs/ukywgEV2nWmYmzPgavv2S117Hro=', 'Josefa', 'Morales', '20000000-0000-4000-8000-000000000003', 5, '30000000-0000-4000-8000-000000000003', true, false, false, '2026-09-14 11:20:00+00', '2026-09-26 12:00:00+00'),
    ('10000000-0000-4000-8000-000000000007', 'tomas.demo@duocuc.cl', 'pbkdf2_sha256$1000000$VJA1yj0q6cLJzKqMv9KVW8$2jrwCPc3HL8Ve1XcgUhWayK+lRINDEosjre9UGf6TyA=', 'Tomás', 'Vidal', NULL, NULL, NULL, false, true, false, '2026-09-29 23:00:00+00', '2026-09-29 23:00:00+00'),
    ('10000000-0000-4000-8000-000000000008', 'admin.demo@duocuc.cl', 'pbkdf2_sha256$1000000$c5353jPzqZj2OSwl8T9JVk$vA14vZUXbskthN7sRKsCrhxoVRjxvZyh6gla52jp/YQ=', 'Admin', 'Demo', NULL, NULL, NULL, true, true, true, '2026-09-09 12:00:00+00', '2026-09-09 12:00:00+00');

-- Token vigente de Tomas (sin verificar). En claro es 'demo-verificacion-tomas-2026':
-- en la base solo queda su sha256 (ajuste A-12). Vence 24 horas despues de cargar estos datos.
INSERT INTO token_verificacion (usuario_id, token_hash, expira_en, usado_en, creado_en) VALUES
    ('10000000-0000-4000-8000-000000000004', '23c164d69e8c1da629caa1fc62111bdc0239ba586c2b9f993efb47f0421061fd', '2026-09-13 16:40:00+00', '2026-09-12 17:02:00+00', '2026-09-12 16:40:00+00'),
    ('10000000-0000-4000-8000-000000000007', 'b1f29c0a707b43961223422b956e464134b33762f358d0892d7215370bc2c8cc', now() + interval '24 hours', NULL, now());

-- Sesiones ya cerradas: un cierre de sesion y la revocacion al desactivar a Josefa.
INSERT INTO refresh_token (usuario_id, token_hash, expira_en, revocado_en, creado_en) VALUES
    ('10000000-0000-4000-8000-000000000001', 'c1fc9d4ca8b336eb27603ea2e417350298c1f5b72353b3f9d498578126f32a8d', '2026-10-06 13:00:00+00', '2026-09-29 15:00:00+00', '2026-09-29 13:00:00+00'),
    ('10000000-0000-4000-8000-000000000006', '667b77c3f1e72b9cd3a5c3d75a1f88d702828bc7c58b736c969224f4eadadb4d', '2026-10-02 10:00:00+00', '2026-09-26 12:00:00+00', '2026-09-25 10:00:00+00');

-- Avisos: referencia_id es la reserva de tutoring_db que origino el correo.
INSERT INTO aviso_correo (usuario_id, plantilla, asunto, referencia_id, estado, error, enviado_en) VALUES
    ('10000000-0000-4000-8000-000000000004', 'VERIFICACION_CORREO', 'Verifica tu correo · Plataforma de Tutorías', NULL, 'ENVIADO', NULL, '2026-09-12 16:40:00+00'),
    ('10000000-0000-4000-8000-000000000007', 'VERIFICACION_CORREO', 'Verifica tu correo · Plataforma de Tutorías', NULL, 'ENVIADO', NULL, '2026-09-29 23:00:00+00'),
    ('10000000-0000-4000-8000-000000000001', 'SOLICITUD_RECIBIDA', 'Nueva solicitud de tutoría: Programación de Algoritmos', '70000000-0000-4000-8000-000000000004', 'ENVIADO', NULL, '2026-09-29 18:00:00+00'),
    ('10000000-0000-4000-8000-000000000004', 'RESERVA_CONFIRMADA', 'Tu tutoría de Desarrollo Web está confirmada', '70000000-0000-4000-8000-000000000003', 'ENVIADO', NULL, '2026-09-29 12:00:00+00'),
    ('10000000-0000-4000-8000-000000000004', 'RESERVA_RECHAZADA', 'Tu solicitud de Matemática Aplicada fue rechazada', '70000000-0000-4000-8000-000000000005', 'ENVIADO', NULL, '2026-09-27 20:00:00+00'),
    ('10000000-0000-4000-8000-000000000002', 'RESERVA_CANCELADA', 'Se canceló la tutoría de Programación de Algoritmos', '70000000-0000-4000-8000-000000000006', 'ENVIADO', NULL, '2026-09-28 10:00:00+00'),
    ('10000000-0000-4000-8000-000000000006', 'CUENTA_DESACTIVADA', 'Tu cuenta fue desactivada', NULL, 'FALLIDO', 'Tiempo de espera agotado al conectar con el servidor de correo', '2026-09-26 12:00:00+00');

COMMIT;

-- Resumen de lo cargado
SELECT 'usuario' AS tabla, count(*) AS filas FROM usuario
UNION ALL SELECT 'token_verificacion' AS tabla, count(*) AS filas FROM token_verificacion
UNION ALL SELECT 'refresh_token' AS tabla, count(*) AS filas FROM refresh_token
UNION ALL SELECT 'aviso_correo' AS tabla, count(*) AS filas FROM aviso_correo;
