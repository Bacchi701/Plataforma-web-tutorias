-- Demostracion: la base de Identidad rechaza lo que el anexo A prohibe.
\set ON_ERROR_STOP off
\set ON_ERROR_ROLLBACK on
\set VERBOSITY terse
BEGIN;

\echo
\echo '1. RN-08: un correo que no es @duocuc.cl'
INSERT INTO usuario (id, email, password_hash, nombre, apellido, email_verificado, activo,
                     es_admin, creado_en, actualizado_en)
VALUES (gen_random_uuid(), 'alguien@gmail.com', 'x', 'Alguien', 'Externo', false, true,
        false, now(), now());

\echo
\echo '2. RN-08: el mismo correo de Valentina, pero con mayusculas'
INSERT INTO usuario (id, email, password_hash, nombre, apellido, email_verificado, activo,
                     es_admin, creado_en, actualizado_en)
VALUES (gen_random_uuid(), 'VALENTINA.DEMO@duocuc.cl', 'x', 'Valentina', 'Copia', false, true,
        false, now(), now());

\echo
\echo '3. Perfil: nivel 13 (el rango es 1 a 12)'
UPDATE usuario SET nivel = 13 WHERE email = 'camila.demo@duocuc.cl';

\echo
\echo '4. A-08: el mismo aviso dos veces para la misma reserva (idempotencia)'
INSERT INTO aviso_correo (usuario_id, plantilla, asunto, referencia_id, estado, enviado_en)
VALUES ('10000000-0000-4000-8000-000000000004', 'RESERVA_CONFIRMADA', 'Repetido',
        '70000000-0000-4000-8000-000000000003', 'ENVIADO', now());

ROLLBACK;
\echo
\echo 'Listo: todo se deshizo con ROLLBACK.'
