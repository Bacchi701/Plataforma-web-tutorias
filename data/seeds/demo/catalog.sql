-- Datos FICTICIOS de ejemplo para catalog_db (demostracion, semana 8).
-- Ninguna persona es real: los correos son inventados (nombre.demo@duocuc.cl)
-- Las mallas son recortes de prueba (Pilar 5, 9.4), no las mallas oficiales.
-- Los identificadores son los mismos en las cuatro bases, para que se pueda
-- seguir una reserva de una base a otra.
-- Se puede ejecutar las veces que haga falta: vacia sus tablas y las llena.
-- Uso: .\scripts\cargar_datos_demo.ps1  (o los dos comandos del RUNBOOK).

\set ON_ERROR_STOP on
BEGIN;

TRUNCATE importacion_error, importacion_catalogo, prerrequisito, malla_asignatura, malla, asignatura, carrera, sede RESTART IDENTITY CASCADE;

-- Sedes (los nombres de las maquetas de registro).
INSERT INTO sede (id, codigo, nombre, region, activa) VALUES
    ('30000000-0000-4000-8000-000000000001', 'ALAMEDA', 'Alameda', 'Metropolitana', true),
    ('30000000-0000-4000-8000-000000000002', 'ANTONIO-VARAS', 'Antonio Varas', 'Metropolitana', true),
    ('30000000-0000-4000-8000-000000000003', 'MAIPU', 'Maipú', 'Metropolitana', true),
    ('30000000-0000-4000-8000-000000000004', 'PLAZA-OESTE', 'Plaza Oeste', 'Metropolitana', true),
    ('30000000-0000-4000-8000-000000000005', 'PLAZA-NORTE', 'Plaza Norte', 'Metropolitana', true),
    ('30000000-0000-4000-8000-000000000006', 'SAN-BERNARDO', 'San Bernardo', 'Metropolitana', true),
    ('30000000-0000-4000-8000-000000000007', 'PUENTE-ALTO', 'Puente Alto', 'Metropolitana', true),
    ('30000000-0000-4000-8000-000000000008', 'VINA-DEL-MAR', 'Viña del Mar', 'Valparaíso', true),
    ('30000000-0000-4000-8000-000000000009', 'VALPARAISO', 'Valparaíso', 'Valparaíso', true),
    ('30000000-0000-4000-8000-000000000010', 'CONCEPCION', 'Concepción', 'Biobío', true),
    ('30000000-0000-4000-8000-000000000011', 'SAN-JOAQUIN', 'San Joaquín', 'Metropolitana', true);

-- Carreras. La ultima esta cerrada (borrado logico): GET /carreras no la muestra.
INSERT INTO carrera (id, codigo, nombre, escuela, activa, creada_en) VALUES
    ('20000000-0000-4000-8000-000000000001', 'ING-INFO', 'Ingeniería en Informática', 'Informática y Telecomunicaciones', true, '2026-09-20 15:00:00+00'),
    ('20000000-0000-4000-8000-000000000002', 'ANA-PROG', 'Analista Programador Computacional', 'Informática y Telecomunicaciones', true, '2026-09-20 15:00:00+00'),
    ('20000000-0000-4000-8000-000000000003', 'ING-ADM', 'Ingeniería en Administración', 'Administración y Negocios', true, '2026-09-20 15:00:00+00'),
    ('20000000-0000-4000-8000-000000000004', 'DIS-GRAF', 'Diseño Gráfico', 'Comunicación', false, '2026-09-20 15:00:00+00');

-- Asignaturas: transversales entre carreras (Pilar 2, 6.2).
INSERT INTO asignatura (id, sigla, nombre, creditos, activa, creada_en) VALUES
    ('40000000-0000-4000-8000-000000000001', 'MAT1101', 'Matemática Aplicada', 6, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000002', 'ING1101', 'Inglés Elemental', 4, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000003', 'ETI1101', 'Ética para el Trabajo', 3, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000004', 'EST2101', 'Estadística Descriptiva', 5, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000005', 'PRO1101', 'Programación de Algoritmos', 8, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000006', 'BDD1101', 'Base de Datos', 6, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000007', 'PRO2101', 'Programación Orientada a Objetos', 8, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000008', 'WEB2101', 'Desarrollo Web', 6, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000009', 'BDD2101', 'Programación de Base de Datos', 6, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000010', 'RED1101', 'Fundamentos de Redes', 5, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000011', 'SIS3101', 'Arquitectura de Software', 6, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000012', 'MOV3101', 'Desarrollo de Aplicaciones Móviles', 6, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000013', 'SEG3101', 'Seguridad en Sistemas', 5, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000014', 'ING2101', 'Inglés Intermedio', 4, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000015', 'ADM1101', 'Fundamentos de Administración', 6, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000016', 'CON1101', 'Contabilidad Básica', 6, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000017', 'ECO2101', 'Microeconomía', 5, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000018', 'FIN2101', 'Matemática Financiera', 5, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000019', 'MKT3101', 'Marketing', 5, true, '2026-09-20 15:00:00+00'),
    ('40000000-0000-4000-8000-000000000020', 'RRH3101', 'Gestión de Personas', 5, true, '2026-09-20 15:00:00+00');

-- Mallas: una vigente por carrera (vigente_hasta NULL) y una antigua de Ingenieria en Informatica.
INSERT INTO malla (carrera_id, version, vigente_desde, vigente_hasta, creada_en) VALUES
    ((SELECT id FROM carrera WHERE codigo = 'ING-INFO'), '2024', '2024-03-01', NULL, '2026-09-20 15:00:00+00'),
    ((SELECT id FROM carrera WHERE codigo = 'ING-INFO'), '2020', '2020-03-01', '2024-02-29', '2026-09-20 15:00:00+00'),
    ((SELECT id FROM carrera WHERE codigo = 'ANA-PROG'), '2024', '2024-03-01', NULL, '2026-09-20 15:00:00+00'),
    ((SELECT id FROM carrera WHERE codigo = 'ING-ADM'), '2023', '2023-03-01', NULL, '2026-09-20 15:00:00+00');

-- Asignaturas de cada malla, por semestre.
-- ING-INFO 2024
INSERT INTO malla_asignatura (malla_id, asignatura_id, semestre) VALUES
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000001', 1),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000005', 1),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000006', 1),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000003', 1),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000007', 2),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000002', 2),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000010', 2),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000004', 2),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000008', 3),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000009', 3),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000014', 3),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000011', 4),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000012', 4),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024'), '40000000-0000-4000-8000-000000000013', 4);
-- ING-INFO 2020
INSERT INTO malla_asignatura (malla_id, asignatura_id, semestre) VALUES
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2020'), '40000000-0000-4000-8000-000000000001', 1),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2020'), '40000000-0000-4000-8000-000000000005', 1),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2020'), '40000000-0000-4000-8000-000000000006', 2),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-INFO' AND m.version = '2020'), '40000000-0000-4000-8000-000000000007', 2);
-- ANA-PROG 2024
INSERT INTO malla_asignatura (malla_id, asignatura_id, semestre) VALUES
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ANA-PROG' AND m.version = '2024'), '40000000-0000-4000-8000-000000000001', 1),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ANA-PROG' AND m.version = '2024'), '40000000-0000-4000-8000-000000000005', 1),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ANA-PROG' AND m.version = '2024'), '40000000-0000-4000-8000-000000000006', 1),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ANA-PROG' AND m.version = '2024'), '40000000-0000-4000-8000-000000000007', 2),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ANA-PROG' AND m.version = '2024'), '40000000-0000-4000-8000-000000000008', 2),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ANA-PROG' AND m.version = '2024'), '40000000-0000-4000-8000-000000000002', 2),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ANA-PROG' AND m.version = '2024'), '40000000-0000-4000-8000-000000000009', 3),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ANA-PROG' AND m.version = '2024'), '40000000-0000-4000-8000-000000000012', 3),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ANA-PROG' AND m.version = '2024'), '40000000-0000-4000-8000-000000000011', 4),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ANA-PROG' AND m.version = '2024'), '40000000-0000-4000-8000-000000000003', 4);
-- ING-ADM 2023
INSERT INTO malla_asignatura (malla_id, asignatura_id, semestre) VALUES
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-ADM' AND m.version = '2023'), '40000000-0000-4000-8000-000000000015', 1),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-ADM' AND m.version = '2023'), '40000000-0000-4000-8000-000000000001', 1),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-ADM' AND m.version = '2023'), '40000000-0000-4000-8000-000000000002', 1),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-ADM' AND m.version = '2023'), '40000000-0000-4000-8000-000000000016', 2),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-ADM' AND m.version = '2023'), '40000000-0000-4000-8000-000000000004', 2),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-ADM' AND m.version = '2023'), '40000000-0000-4000-8000-000000000003', 2),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-ADM' AND m.version = '2023'), '40000000-0000-4000-8000-000000000017', 3),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-ADM' AND m.version = '2023'), '40000000-0000-4000-8000-000000000018', 3),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-ADM' AND m.version = '2023'), '40000000-0000-4000-8000-000000000019', 4),
    ((SELECT m.id FROM malla m JOIN carrera c ON c.id = m.carrera_id WHERE c.codigo = 'ING-ADM' AND m.version = '2023'), '40000000-0000-4000-8000-000000000020', 4);

-- Prerrequisitos (estructura preparada, sin uso en el MVP). Ambos extremos en la misma malla.
INSERT INTO prerrequisito (malla_asignatura_id, requiere_id) VALUES
    ((SELECT ma.id FROM malla_asignatura ma JOIN malla m ON m.id = ma.malla_id JOIN carrera c ON c.id = m.carrera_id JOIN asignatura a ON a.id = ma.asignatura_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024' AND a.sigla = 'PRO2101'), (SELECT ma.id FROM malla_asignatura ma JOIN malla m ON m.id = ma.malla_id JOIN carrera c ON c.id = m.carrera_id JOIN asignatura a ON a.id = ma.asignatura_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024' AND a.sigla = 'PRO1101')),
    ((SELECT ma.id FROM malla_asignatura ma JOIN malla m ON m.id = ma.malla_id JOIN carrera c ON c.id = m.carrera_id JOIN asignatura a ON a.id = ma.asignatura_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024' AND a.sigla = 'BDD2101'), (SELECT ma.id FROM malla_asignatura ma JOIN malla m ON m.id = ma.malla_id JOIN carrera c ON c.id = m.carrera_id JOIN asignatura a ON a.id = ma.asignatura_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024' AND a.sigla = 'BDD1101')),
    ((SELECT ma.id FROM malla_asignatura ma JOIN malla m ON m.id = ma.malla_id JOIN carrera c ON c.id = m.carrera_id JOIN asignatura a ON a.id = ma.asignatura_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024' AND a.sigla = 'SIS3101'), (SELECT ma.id FROM malla_asignatura ma JOIN malla m ON m.id = ma.malla_id JOIN carrera c ON c.id = m.carrera_id JOIN asignatura a ON a.id = ma.asignatura_id WHERE c.codigo = 'ING-INFO' AND m.version = '2024' AND a.sigla = 'PRO2101')),
    ((SELECT ma.id FROM malla_asignatura ma JOIN malla m ON m.id = ma.malla_id JOIN carrera c ON c.id = m.carrera_id JOIN asignatura a ON a.id = ma.asignatura_id WHERE c.codigo = 'ANA-PROG' AND m.version = '2024' AND a.sigla = 'PRO2101'), (SELECT ma.id FROM malla_asignatura ma JOIN malla m ON m.id = ma.malla_id JOIN carrera c ON c.id = m.carrera_id JOIN asignatura a ON a.id = ma.asignatura_id WHERE c.codigo = 'ANA-PROG' AND m.version = '2024' AND a.sigla = 'PRO1101')),
    ((SELECT ma.id FROM malla_asignatura ma JOIN malla m ON m.id = ma.malla_id JOIN carrera c ON c.id = m.carrera_id JOIN asignatura a ON a.id = ma.asignatura_id WHERE c.codigo = 'ING-ADM' AND m.version = '2023' AND a.sigla = 'FIN2101'), (SELECT ma.id FROM malla_asignatura ma JOIN malla m ON m.id = ma.malla_id JOIN carrera c ON c.id = m.carrera_id JOIN asignatura a ON a.id = ma.asignatura_id WHERE c.codigo = 'ING-ADM' AND m.version = '2023' AND a.sigla = 'MAT1101'));

-- Una carga desde CSV con una fila rechazada. El error queda en su propia tabla (1FN).
INSERT INTO importacion_catalogo (archivo, tipo, filas_leidas, filas_creadas, filas_omitidas, ejecutada_por, ejecutada_en) VALUES
    ('ejemplo_sedes.csv', 'SEDES', 11, 11, 0, NULL, '2026-09-20 14:55:00+00'),
    ('ejemplo_malla_ing_informatica_2024.csv', 'MALLA', 15, 14, 1, NULL, '2026-09-20 15:00:00+00');
INSERT INTO importacion_error (importacion_id, fila, mensaje) VALUES
    ((SELECT id FROM importacion_catalogo WHERE archivo = 'ejemplo_malla_ing_informatica_2024.csv'), 16, 'Semestre 13 fuera del rango de 1 a 12 (asignatura SEG3101): se omite la fila');

COMMIT;

-- Resumen de lo cargado
SELECT 'sede' AS tabla, count(*) AS filas FROM sede
UNION ALL SELECT 'carrera' AS tabla, count(*) AS filas FROM carrera
UNION ALL SELECT 'malla' AS tabla, count(*) AS filas FROM malla
UNION ALL SELECT 'asignatura' AS tabla, count(*) AS filas FROM asignatura
UNION ALL SELECT 'malla_asignatura' AS tabla, count(*) AS filas FROM malla_asignatura
UNION ALL SELECT 'prerrequisito' AS tabla, count(*) AS filas FROM prerrequisito
UNION ALL SELECT 'importacion_catalogo' AS tabla, count(*) AS filas FROM importacion_catalogo
UNION ALL SELECT 'importacion_error' AS tabla, count(*) AS filas FROM importacion_error;
