-- Demostracion: la base de Catalogo rechaza lo que el anexo A prohibe.
\set ON_ERROR_STOP off
\set ON_ERROR_ROLLBACK on
\set VERBOSITY terse
BEGIN;

\echo
\echo '1. Una segunda malla vigente para Ingenieria en Informatica'
INSERT INTO malla (carrera_id, version, vigente_desde, vigente_hasta, creada_en)
VALUES ('20000000-0000-4000-8000-000000000001', '2026', '2026-03-01', NULL, now());

\echo
\echo '2. RN-01: una asignatura en el semestre 13'
INSERT INTO malla_asignatura (malla_id, asignatura_id, semestre)
SELECT m.id, '40000000-0000-4000-8000-000000000020', 13
FROM malla m WHERE m.carrera_id = '20000000-0000-4000-8000-000000000001' AND m.version = '2024';

\echo
\echo '3. Una sigla repetida'
INSERT INTO asignatura (id, sigla, nombre, creditos, activa, creada_en)
VALUES (gen_random_uuid(), 'PRO1101', 'Otra con la misma sigla', 4, true, now());

\echo
\echo '4. Un prerrequisito de una asignatura consigo misma'
INSERT INTO prerrequisito (malla_asignatura_id, requiere_id)
SELECT id, id FROM malla_asignatura LIMIT 1;

ROLLBACK;
\echo
\echo 'Listo: todo se deshizo con ROLLBACK.'
