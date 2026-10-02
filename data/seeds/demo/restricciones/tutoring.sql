-- Demostracion: la base de Tutorias rechaza lo que el anexo A prohibe.
-- Cada intento deberia terminar en ERROR. Todo corre dentro de una transaccion
-- que se deshace al final: los datos de ejemplo quedan intactos.
\set ON_ERROR_STOP off
\set ON_ERROR_ROLLBACK on
\set VERBOSITY terse
BEGIN;

\echo
\echo '1. RN-02: Valentina publica un bloque que se solapa con otro suyo (5-oct, 20:00 a 21:00 UTC)'
INSERT INTO bloque_disponibilidad (id, usuario_id, inicio_en, fin_en, estado, creado_en, actualizado_en)
VALUES (gen_random_uuid(), '10000000-0000-4000-8000-000000000001',
        '2026-10-05 20:30+00', '2026-10-05 21:30+00', 'LIBRE', now(), now());

\echo
\echo '2. RN-02 con borrado logico: Matias publica un bloque encima de uno ELIMINADO (debe ACEPTARSE)'
INSERT INTO bloque_disponibilidad (id, usuario_id, inicio_en, fin_en, estado, creado_en, actualizado_en)
VALUES (gen_random_uuid(), '10000000-0000-4000-8000-000000000002',
        '2026-10-06 21:30+00', '2026-10-06 21:59+00', 'LIBRE', now(), now())
RETURNING 'aceptado: el bloque eliminado no cuenta' AS resultado;

\echo
\echo '3. RN-03: Valentina intenta reservar su propio bloque (lo frena el disparador)'
INSERT INTO reserva (id, bloque_id, solicitante_usuario_id, asignatura_id, estado, monto, creada_en)
VALUES (gen_random_uuid(), '60000000-0000-4000-8000-000000000009',
        '10000000-0000-4000-8000-000000000001', '40000000-0000-4000-8000-000000000005',
        'SOLICITADA', 0, now());

\echo
\echo '4. RN-03: Diego pide otra vez el mismo bloque que ya tiene solicitado'
INSERT INTO reserva (id, bloque_id, solicitante_usuario_id, asignatura_id, estado, monto, creada_en)
VALUES (gen_random_uuid(), '60000000-0000-4000-8000-000000000004',
        '10000000-0000-4000-8000-000000000005', '40000000-0000-4000-8000-000000000005',
        'SOLICITADA', 0, now());

\echo
\echo '5. RN-03 / A-03: una segunda reserva confirmada sobre un bloque ya ocupado'
INSERT INTO reserva (id, bloque_id, solicitante_usuario_id, asignatura_id, estado, modalidad,
                     lugar_o_enlace, monto, creada_en, confirmada_en)
VALUES (gen_random_uuid(), '60000000-0000-4000-8000-000000000003',
        '10000000-0000-4000-8000-000000000005', '40000000-0000-4000-8000-000000000008',
        'CONFIRMADA', 'EN_LINEA', 'https://meet.example.com/otra', 4000, now(), now());

\echo
\echo '6. RN-07: confirmar la solicitud de Diego sin modalidad ni lugar'
UPDATE reserva SET estado = 'CONFIRMADA', confirmada_en = now()
WHERE id = '70000000-0000-4000-8000-000000000004';

\echo
\echo '7. RN-05: poner estado de pago a una tutoria gratuita (monto 0)'
UPDATE reserva SET estado_pago = 'PENDIENTE'
WHERE id = '70000000-0000-4000-8000-000000000004';

\echo
\echo '8. RF-03: Valentina declara dos veces Programacion de Algoritmos'
INSERT INTO perfil_tutor (id, usuario_id, asignatura_id, tarifa, activo, creado_en, actualizado_en)
VALUES (gen_random_uuid(), '10000000-0000-4000-8000-000000000001',
        '40000000-0000-4000-8000-000000000005', 1000, true, now(), now());

\echo
\echo '9. RN-05: tarifa negativa'
INSERT INTO perfil_tutor (id, usuario_id, asignatura_id, tarifa, activo, creado_en, actualizado_en)
VALUES (gen_random_uuid(), '10000000-0000-4000-8000-000000000003',
        '40000000-0000-4000-8000-000000000008', -500, true, now(), now());

\echo
\echo '10. RN-06: calificacion 6 en una escala de 1 a 5'
UPDATE evaluacion SET calificacion = 6 WHERE id = '80000000-0000-4000-8000-000000000001';

ROLLBACK;
\echo
\echo 'Listo: todo se deshizo con ROLLBACK.'
