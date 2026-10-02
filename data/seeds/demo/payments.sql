-- Datos FICTICIOS de ejemplo para payment_db (demostracion, semana 8).
-- Ninguna persona es real: los correos son inventados (nombre.demo@duocuc.cl)
-- Pagos solo conoce reservas y montos: ni usuarios ni asignaturas.
-- Los identificadores son los mismos en las cuatro bases, para que se pueda
-- seguir una reserva de una base a otra.
-- Se puede ejecutar las veces que haga falta: vacia sus tablas y las llena.
-- Uso: .\scripts\cargar_datos_demo.ps1  (o los dos comandos del RUNBOOK).

\set ON_ERROR_STOP on
BEGIN;

TRUNCATE intento_pago, pago RESTART IDENTITY CASCADE;

-- Un pago por reserva con tarifa mayor que cero que llego a confirmarse.
-- reserva_id es la reserva de tutoring_db (referencia logica, sin FK).
INSERT INTO pago (id, reserva_id, monto, estado, proveedor, referencia_externa, notificado_en, creado_en, actualizado_en) VALUES
    ('90000000-0000-4000-8000-000000000001', '70000000-0000-4000-8000-000000000001', 5000, 'PAGADO', 'SIMULADO', 'SIM-2026-0001', '2026-09-18 20:05:00+00', '2026-09-18 20:00:30+00', '2026-09-18 20:05:00+00'),
    ('90000000-0000-4000-8000-000000000002', '70000000-0000-4000-8000-000000000002', 6000, 'PAGADO', 'SIMULADO', 'SIM-2026-0002', '2026-09-22 22:10:00+00', '2026-09-22 22:00:30+00', '2026-09-22 22:10:00+00'),
    ('90000000-0000-4000-8000-000000000003', '70000000-0000-4000-8000-000000000003', 4000, 'PENDIENTE', 'SIMULADO', NULL, '2026-09-29 12:01:00+00', '2026-09-29 12:00:30+00', '2026-09-29 12:00:30+00'),
    ('90000000-0000-4000-8000-000000000004', '70000000-0000-4000-8000-000000000006', 3000, 'REEMBOLSADO', 'SIMULADO', 'SIM-2026-0003', '2026-09-28 10:02:00+00', '2026-09-25 18:00:30+00', '2026-09-28 10:01:00+00');

-- Historial: un cobro rechazado y reintentado (RN-05) y un reembolso (CA9).
INSERT INTO intento_pago (pago_id, tipo, resultado, mensaje, referencia_externa, creado_en) VALUES
    ('90000000-0000-4000-8000-000000000001', 'COBRO', 'FALLIDO', 'Rechazado por el simulador: fondos insuficientes.', 'SIM-2026-0001-A', '2026-09-18 20:02:00+00'),
    ('90000000-0000-4000-8000-000000000001', 'COBRO', 'EXITOSO', NULL, 'SIM-2026-0001', '2026-09-18 20:05:00+00'),
    ('90000000-0000-4000-8000-000000000002', 'COBRO', 'EXITOSO', NULL, 'SIM-2026-0002', '2026-09-22 22:10:00+00'),
    ('90000000-0000-4000-8000-000000000004', 'COBRO', 'EXITOSO', NULL, 'SIM-2026-0003', '2026-09-25 18:05:00+00'),
    ('90000000-0000-4000-8000-000000000004', 'REEMBOLSO', 'EXITOSO', NULL, 'SIM-2026-0003-R', '2026-09-28 10:01:00+00');

COMMIT;

-- Resumen de lo cargado
SELECT 'pago' AS tabla, count(*) AS filas FROM pago
UNION ALL SELECT 'intento_pago' AS tabla, count(*) AS filas FROM intento_pago;
