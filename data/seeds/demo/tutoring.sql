-- Datos FICTICIOS de ejemplo para tutoring_db (demostracion, semana 8).
-- Ninguna persona es real: los correos son inventados (nombre.demo@duocuc.cl)
-- Las cuentas y sus claves viven en identity_db.
-- Los identificadores son los mismos en las cuatro bases, para que se pueda
-- seguir una reserva de una base a otra.
-- Se puede ejecutar las veces que haga falta: vacia sus tablas y las llena.
-- Uso: .\scripts\cargar_datos_demo.ps1  (o los dos comandos del RUNBOOK).

\set ON_ERROR_STOP on
BEGIN;

TRUNCATE evaluacion, reserva, bloque_disponibilidad, perfil_tutor, asignatura_ref, usuario_ref, ejecucion_tarea RESTART IDENTITY CASCADE;

-- Copias de lectura de identity_db (AD-07). Solo quienes ya tocaron Tutorias.
-- Sin carrera_nombre ni sede_nombre (3FN). Josefa esta desactivada: no aparece en busquedas.
-- La reputacion sale de las evaluaciones visibles; la retirada no cuenta.
INSERT INTO usuario_ref (usuario_id, nombre, apellido, carrera_id, sede_id, activo, reputacion_promedio, reputacion_total, actualizado_en) VALUES
    ('10000000-0000-4000-8000-000000000001', 'Valentina', 'Soto', '20000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000011', true, 5.00, 1, '2026-09-26 14:05:00+00'),
    ('10000000-0000-4000-8000-000000000002', 'Matías', 'Fuentes', '20000000-0000-4000-8000-000000000002', '30000000-0000-4000-8000-000000000004', true, 0.00, 0, '2026-09-26 14:05:00+00'),
    ('10000000-0000-4000-8000-000000000003', 'Fernanda', 'Castro', '20000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000001', true, 0.00, 0, '2026-09-26 14:05:00+00'),
    ('10000000-0000-4000-8000-000000000004', 'Camila', 'Rojas', '20000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000011', true, 0.00, 0, '2026-09-26 14:05:00+00'),
    ('10000000-0000-4000-8000-000000000005', 'Diego', 'Herrera', '20000000-0000-4000-8000-000000000002', '30000000-0000-4000-8000-000000000004', true, 0.00, 0, '2026-09-26 14:05:00+00'),
    ('10000000-0000-4000-8000-000000000006', 'Josefa', 'Morales', '20000000-0000-4000-8000-000000000003', '30000000-0000-4000-8000-000000000003', false, 0.00, 0, '2026-09-26 14:05:00+00');

-- Copias de lectura de catalog_db.asignatura.
INSERT INTO asignatura_ref (asignatura_id, sigla, nombre, actualizado_en) VALUES
    ('40000000-0000-4000-8000-000000000005', 'PRO1101', 'Programación de Algoritmos', '2026-09-26 14:05:00+00'),
    ('40000000-0000-4000-8000-000000000006', 'BDD1101', 'Base de Datos', '2026-09-26 14:05:00+00'),
    ('40000000-0000-4000-8000-000000000008', 'WEB2101', 'Desarrollo Web', '2026-09-26 14:05:00+00'),
    ('40000000-0000-4000-8000-000000000010', 'RED1101', 'Fundamentos de Redes', '2026-09-26 14:05:00+00'),
    ('40000000-0000-4000-8000-000000000001', 'MAT1101', 'Matemática Aplicada', '2026-09-26 14:05:00+00'),
    ('40000000-0000-4000-8000-000000000016', 'CON1101', 'Contabilidad Básica', '2026-09-26 14:05:00+00');

-- Asignaturas que cada tutor declaro, con su tarifa en pesos (0 = gratuita).
INSERT INTO perfil_tutor (id, usuario_id, asignatura_id, tarifa, descripcion, activo, creado_en, actualizado_en) VALUES
    ('50000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000001', '40000000-0000-4000-8000-000000000005', 0, 'Te ayudo con algoritmos desde cero, con ejercicios guiados.', true, '2026-09-15 13:00:00+00', '2026-09-15 13:00:00+00'),
    ('50000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000001', '40000000-0000-4000-8000-000000000006', 5000, 'Modelo entidad-relación, normalización y SQL.', true, '2026-09-15 13:05:00+00', '2026-09-15 13:05:00+00'),
    ('50000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000002', '40000000-0000-4000-8000-000000000005', 3000, 'Resolución de guías y preparación de pruebas.', true, '2026-09-16 15:00:00+00', '2026-09-16 15:00:00+00'),
    ('50000000-0000-4000-8000-000000000004', '10000000-0000-4000-8000-000000000002', '40000000-0000-4000-8000-000000000008', 4000, 'HTML, CSS y JavaScript para tus entregas.', true, '2026-09-16 15:10:00+00', '2026-09-16 15:10:00+00'),
    ('50000000-0000-4000-8000-000000000005', '10000000-0000-4000-8000-000000000003', '40000000-0000-4000-8000-000000000010', 6000, 'Subredes, modelo OSI y laboratorios de Packet Tracer.', true, '2026-09-17 12:30:00+00', '2026-09-17 12:30:00+00'),
    ('50000000-0000-4000-8000-000000000006', '10000000-0000-4000-8000-000000000003', '40000000-0000-4000-8000-000000000001', 0, 'Álgebra y funciones, a tu ritmo.', true, '2026-09-17 12:40:00+00', '2026-09-17 12:40:00+00'),
    ('50000000-0000-4000-8000-000000000007', '10000000-0000-4000-8000-000000000006', '40000000-0000-4000-8000-000000000016', 2000, 'Asientos contables y balances.', true, '2026-09-18 10:00:00+00', '2026-09-18 10:00:00+00');

-- Bloques de disponibilidad, en UTC (la hora de Chile la calcula el cliente).
-- OCUPADO = tiene una reserva confirmada, realizada o evaluada.
INSERT INTO bloque_disponibilidad (id, usuario_id, inicio_en, fin_en, estado, creado_en, actualizado_en) VALUES
    ('60000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000001', '2026-09-21 21:00:00+00', '2026-09-21 22:00:00+00', 'OCUPADO', '2026-09-17 14:00:00+00', '2026-09-18 20:00:00+00'),
    ('60000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000003', '2026-09-24 18:00:00+00', '2026-09-24 19:30:00+00', 'OCUPADO', '2026-09-21 15:00:00+00', '2026-09-22 22:00:00+00'),
    ('60000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000002', '2026-10-06 22:00:00+00', '2026-10-06 23:00:00+00', 'OCUPADO', '2026-09-27 16:00:00+00', '2026-09-29 12:00:00+00'),
    ('60000000-0000-4000-8000-000000000004', '10000000-0000-4000-8000-000000000001', '2026-10-05 20:00:00+00', '2026-10-05 21:00:00+00', 'LIBRE', '2026-09-28 18:00:00+00', '2026-09-28 18:00:00+00'),
    ('60000000-0000-4000-8000-000000000005', '10000000-0000-4000-8000-000000000003', '2026-10-08 13:00:00+00', '2026-10-08 14:00:00+00', 'LIBRE', '2026-09-26 12:00:00+00', '2026-09-26 12:00:00+00'),
    ('60000000-0000-4000-8000-000000000006', '10000000-0000-4000-8000-000000000002', '2026-10-07 21:00:00+00', '2026-10-07 22:00:00+00', 'LIBRE', '2026-09-24 14:00:00+00', '2026-09-28 10:00:00+00'),
    ('60000000-0000-4000-8000-000000000007', '10000000-0000-4000-8000-000000000003', '2026-09-26 14:00:00+00', '2026-09-26 15:00:00+00', 'LIBRE', '2026-09-23 12:00:00+00', '2026-09-23 12:00:00+00'),
    ('60000000-0000-4000-8000-000000000008', '10000000-0000-4000-8000-000000000001', '2026-09-23 20:00:00+00', '2026-09-23 21:00:00+00', 'OCUPADO', '2026-09-20 23:00:00+00', '2026-09-22 12:00:00+00'),
    ('60000000-0000-4000-8000-000000000009', '10000000-0000-4000-8000-000000000001', '2026-10-09 19:00:00+00', '2026-10-09 20:30:00+00', 'LIBRE', '2026-09-29 12:00:00+00', '2026-09-29 12:00:00+00'),
    ('60000000-0000-4000-8000-000000000010', '10000000-0000-4000-8000-000000000003', '2026-10-09 15:00:00+00', '2026-10-09 16:00:00+00', 'LIBRE', '2026-09-29 12:00:00+00', '2026-09-29 12:00:00+00'),
    ('60000000-0000-4000-8000-000000000011', '10000000-0000-4000-8000-000000000006', '2026-10-06 18:00:00+00', '2026-10-06 19:00:00+00', 'LIBRE', '2026-09-20 12:00:00+00', '2026-09-20 12:00:00+00'),
    ('60000000-0000-4000-8000-000000000012', '10000000-0000-4000-8000-000000000002', '2026-10-06 21:30:00+00', '2026-10-06 22:30:00+00', 'ELIMINADO', '2026-09-27 12:00:00+00', '2026-09-28 09:00:00+00');

-- Reservas: una en cada estado de la maquina del anexo A (seccion 9).
-- El tutor no se guarda: es el dueno del bloque (3FN).
INSERT INTO reserva (id, bloque_id, solicitante_usuario_id, asignatura_id, estado, nota, modalidad, lugar_o_enlace, monto, estado_pago, pago_actualizado_en, cancelada_por_usuario_id, creada_en, confirmada_en, cerrada_en) VALUES
    ('70000000-0000-4000-8000-000000000001', '60000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000004', '40000000-0000-4000-8000-000000000006', 'EVALUADA', 'Me cuesta la tercera forma normal.', 'EN_LINEA', 'https://meet.example.com/tutoria-bdd', 5000, 'PAGADO', '2026-09-18 20:05:00+00', NULL, '2026-09-18 14:00:00+00', '2026-09-18 20:00:00+00', '2026-09-22 13:00:00+00'),
    ('70000000-0000-4000-8000-000000000002', '60000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000005', '40000000-0000-4000-8000-000000000010', 'REALIZADA', 'Necesito practicar subredes.', 'PRESENCIAL', 'Sede Alameda, biblioteca, sala de estudio 2', 6000, 'PAGADO', '2026-09-22 22:10:00+00', NULL, '2026-09-22 15:00:00+00', '2026-09-22 22:00:00+00', NULL),
    ('70000000-0000-4000-8000-000000000003', '60000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000004', '40000000-0000-4000-8000-000000000008', 'CONFIRMADA', 'Quiero revisar mi proyecto antes de entregarlo.', 'EN_LINEA', 'https://meet.example.com/tutoria-web', 4000, 'PENDIENTE', '2026-09-29 12:01:00+00', NULL, '2026-09-28 16:00:00+00', '2026-09-29 12:00:00+00', NULL),
    ('70000000-0000-4000-8000-000000000004', '60000000-0000-4000-8000-000000000004', '10000000-0000-4000-8000-000000000005', '40000000-0000-4000-8000-000000000005', 'SOLICITADA', 'Necesito repasar ciclos y arreglos antes de la prueba.', NULL, NULL, 0, NULL, NULL, NULL, '2026-09-29 18:00:00+00', NULL, NULL),
    ('70000000-0000-4000-8000-000000000005', '60000000-0000-4000-8000-000000000005', '10000000-0000-4000-8000-000000000004', '40000000-0000-4000-8000-000000000001', 'RECHAZADA', NULL, NULL, NULL, 0, NULL, NULL, NULL, '2026-09-27 12:00:00+00', NULL, '2026-09-27 20:00:00+00'),
    ('70000000-0000-4000-8000-000000000006', '60000000-0000-4000-8000-000000000006', '10000000-0000-4000-8000-000000000005', '40000000-0000-4000-8000-000000000005', 'CANCELADA', 'Repaso de funciones.', 'EN_LINEA', 'https://meet.example.com/tutoria-pro', 3000, 'REEMBOLSADO', '2026-09-28 10:02:00+00', '10000000-0000-4000-8000-000000000005', '2026-09-25 14:00:00+00', '2026-09-25 18:00:00+00', '2026-09-28 10:00:00+00'),
    ('70000000-0000-4000-8000-000000000007', '60000000-0000-4000-8000-000000000007', '10000000-0000-4000-8000-000000000004', '40000000-0000-4000-8000-000000000010', 'EXPIRADA', NULL, NULL, NULL, 6000, NULL, NULL, NULL, '2026-09-24 12:00:00+00', NULL, '2026-09-26 14:05:00+00'),
    ('70000000-0000-4000-8000-000000000008', '60000000-0000-4000-8000-000000000008', '10000000-0000-4000-8000-000000000005', '40000000-0000-4000-8000-000000000005', 'EVALUADA', NULL, 'EN_LINEA', 'https://meet.example.com/tutoria-pro-2', 0, NULL, NULL, NULL, '2026-09-21 23:00:00+00', '2026-09-22 12:00:00+00', '2026-09-24 12:00:00+00');

-- Evaluaciones. La segunda la retiro el administrador (CA7).
INSERT INTO evaluacion (id, reserva_id, calificacion, comentario, retirada_en, retirada_por_usuario_id, creada_en) VALUES
    ('80000000-0000-4000-8000-000000000001', '70000000-0000-4000-8000-000000000001', 5, 'Explicó la normalización con ejemplos claros. Muy recomendable.', NULL, NULL, '2026-09-22 13:00:00+00'),
    ('80000000-0000-4000-8000-000000000002', '70000000-0000-4000-8000-000000000008', 1, 'Comentario fuera de las normas de la comunidad.', '2026-09-25 09:00:00+00', '10000000-0000-4000-8000-000000000008', '2026-09-24 12:00:00+00');

-- Ejecuciones del programador que cerraron y expiraron reservas (AD-10).
INSERT INTO ejecucion_tarea (comando, solicitudes_expiradas, reservas_cerradas, refs_sincronizadas, perfiles_desactivados, error, iniciada_en, terminada_en) VALUES
    ('programador', 0, 1, 5, 0, NULL, '2026-09-21 22:05:00+00', '2026-09-21 22:05:02+00'),
    ('programador', 0, 1, 6, 0, NULL, '2026-09-23 21:05:00+00', '2026-09-23 21:05:01+00'),
    ('programador', 0, 1, 6, 0, NULL, '2026-09-24 19:35:00+00', '2026-09-24 19:35:02+00'),
    ('programador', 1, 0, 6, 0, NULL, '2026-09-26 14:05:00+00', '2026-09-26 14:05:01+00');

COMMIT;

-- Resumen de lo cargado
SELECT 'usuario_ref' AS tabla, count(*) AS filas FROM usuario_ref
UNION ALL SELECT 'asignatura_ref' AS tabla, count(*) AS filas FROM asignatura_ref
UNION ALL SELECT 'perfil_tutor' AS tabla, count(*) AS filas FROM perfil_tutor
UNION ALL SELECT 'bloque_disponibilidad' AS tabla, count(*) AS filas FROM bloque_disponibilidad
UNION ALL SELECT 'reserva' AS tabla, count(*) AS filas FROM reserva
UNION ALL SELECT 'evaluacion' AS tabla, count(*) AS filas FROM evaluacion
UNION ALL SELECT 'ejecucion_tarea' AS tabla, count(*) AS filas FROM ejecucion_tarea;
