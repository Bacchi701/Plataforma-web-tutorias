-- Demostracion: la base de Pagos rechaza lo que el anexo A prohibe.
\set ON_ERROR_STOP off
\set ON_ERROR_ROLLBACK on
\set VERBOSITY terse
BEGIN;

\echo
\echo '1. RN-05: un pago de 0 pesos (sin tarifa no hay pago)'
INSERT INTO pago (id, reserva_id, monto, estado, proveedor, creado_en, actualizado_en)
VALUES (gen_random_uuid(), '70000000-0000-4000-8000-000000000004', 0, 'PENDIENTE', 'SIMULADO',
        now(), now());

\echo
\echo '2. A-10: un segundo pago para la misma reserva (los reintentos van en intento_pago)'
INSERT INTO pago (id, reserva_id, monto, estado, proveedor, creado_en, actualizado_en)
VALUES (gen_random_uuid(), '70000000-0000-4000-8000-000000000001', 5000, 'PENDIENTE', 'SIMULADO',
        now(), now());

ROLLBACK;
\echo
\echo 'Listo: todo se deshizo con ROLLBACK.'
