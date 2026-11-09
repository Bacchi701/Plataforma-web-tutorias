-- Carga de prueba FICTICIA para tutoring_db: las copias de los 500 usuarios
-- de identity.sql, 300 de ellos tutores (HU-34, RNF-02).
-- Ninguna persona es real. Las cuentas y sus claves viven en identity_db.
-- Los identificadores son fijos, para reconocer la carga: usuarios
-- c0000000-0000-4000-8000-<n con 12 digitos> (los mismos de identity_db),
-- perfiles c1000000-... y bloques c2000000-... Ningun identificador de los
-- datos de ejemplo empieza con c.
-- Cumple RN-01: cada perfil es de una asignatura del semestre 1 de la malla
-- vigente de la carrera del tutor, y cada tutor tiene nivel 2 o mas. Asi la
-- sincronizacion de las copias (HU-19), que el programador corre cada 300
-- segundos, no desactiva ningun perfil y la medicion encuentra esta carga.
-- Va despues de los datos de ejemplo y de identity.sql. Volver a cargar los
-- datos de ejemplo borra esta carga.
-- Se puede ejecutar las veces que haga falta: borra la carga anterior, y solo
-- esa, y la vuelve a crear.
-- Uso: .\scripts\cargar_usuarios_prueba.ps1  (o sh scripts/cargar_usuarios_prueba.sh).

\set ON_ERROR_STOP on
BEGIN;

-- Los 500 usuarios de la carga, con su numero n.
CREATE TEMP TABLE carga AS
SELECT n, ('c0000000-0000-4000-8000-' || lpad(n::text, 12, '0'))::uuid AS usuario_id
FROM generate_series(1, 500) AS n;

-- Las cinco asignaturas de la carga, con la sigla y el nombre de
-- data/seeds/demo/catalog.sql. MAT1101, PRO1101 y BDD1101 ya vienen en los
-- datos de ejemplo; ADM1101 e ING1101 no. Esas dos se quedan aunque se vuelva
-- a correr esta carga: son copias de Catalogo.
INSERT INTO asignatura_ref (asignatura_id, sigla, nombre, actualizado_en) VALUES
    ('40000000-0000-4000-8000-000000000001', 'MAT1101', 'Matemática Aplicada', now()),
    ('40000000-0000-4000-8000-000000000002', 'ING1101', 'Inglés Elemental', now()),
    ('40000000-0000-4000-8000-000000000005', 'PRO1101', 'Programación de Algoritmos', now()),
    ('40000000-0000-4000-8000-000000000006', 'BDD1101', 'Base de Datos', now()),
    ('40000000-0000-4000-8000-000000000015', 'ADM1101', 'Fundamentos de Administración', now())
ON CONFLICT (asignatura_id) DO NOTHING;

-- La carga anterior, y solo esa, con las filas hijas antes que las madres: el
-- borrado en cascada lo hace Django, no la base (anexo A, seccion 10). Primero
-- las evaluaciones y las reservas que tocan bloques o solicitantes de la carga.
DELETE FROM evaluacion
WHERE reserva_id IN (
    SELECT r.id
    FROM reserva AS r
    JOIN bloque_disponibilidad AS b ON b.id = r.bloque_id
    WHERE b.usuario_id IN (SELECT usuario_id FROM carga)
       OR r.solicitante_usuario_id IN (SELECT usuario_id FROM carga)
);
DELETE FROM reserva
WHERE bloque_id IN (SELECT id FROM bloque_disponibilidad WHERE usuario_id IN (SELECT usuario_id FROM carga))
   OR solicitante_usuario_id IN (SELECT usuario_id FROM carga);
DELETE FROM bloque_disponibilidad WHERE usuario_id IN (SELECT usuario_id FROM carga);
DELETE FROM perfil_tutor WHERE usuario_id IN (SELECT usuario_id FROM carga);
DELETE FROM usuario_ref WHERE usuario_id IN (SELECT usuario_id FROM carga);

-- Las copias de los 500 usuarios, con los nombres, la carrera y la sede de
-- identity.sql, y activas. Dos de cada tres tienen reputacion (promedio de
-- 3,00 a 5,00, de 1 a 12 evaluaciones) y una de cada tres no tiene
-- evaluaciones (0,00 y 0): las que tienen ((n - 1) div 9) mod 3 = 2, para que
-- haya de las dos en cada carrera y en cada par de asignaturas.
INSERT INTO usuario_ref (usuario_id, nombre, apellido, carrera_id, sede_id, activo, reputacion_promedio, reputacion_total, actualizado_en)
SELECT
    c.usuario_id,
    (ARRAY['Sofía', 'Martina', 'Isidora', 'Florencia', 'Agustina', 'Catalina', 'Antonia', 'Emilia', 'Trinidad', 'Javiera',
           'Benjamín', 'Vicente', 'Martín', 'Joaquín', 'Agustín', 'Cristóbal', 'Maximiliano', 'Lucas', 'Sebastián', 'Felipe'])[(c.n - 1) % 20 + 1],
    (ARRAY['González', 'Muñoz', 'Díaz', 'Pérez', 'Silva', 'Contreras', 'López', 'Martínez', 'Sepúlveda', 'Torres',
           'Araya', 'Flores', 'Espinoza', 'Valenzuela', 'Castillo', 'Ramírez', 'Reyes', 'Gutiérrez', 'Álvarez', 'Vásquez',
           'Tapia', 'Sánchez', 'Fernández', 'Carrasco', 'Cortés'])[(c.n - 1) / 20 + 1],
    ('20000000-0000-4000-8000-' || lpad(((c.n - 1) % 3 + 1)::text, 12, '0'))::uuid,
    ('30000000-0000-4000-8000-' || lpad(((c.n - 1) % 11 + 1)::text, 12, '0'))::uuid,
    true,
    CASE WHEN ((c.n - 1) / 9) % 3 = 2 THEN 0.00 ELSE 3 + ((c.n * 37) % 201) / 100.0 END,
    CASE WHEN ((c.n - 1) / 9) % 3 = 2 THEN 0 ELSE 1 + (c.n * 5) % 12 END,
    now()
FROM carga AS c
ORDER BY c.n;

-- Dos perfiles activos por tutor (usuarios 1 a 300): el par numero
-- ((n - 1) div 3) mod 3 de su carrera, siempre del semestre 1 de su malla
-- vigente. Las asignaturas van por su numero: 40000000-0000-4000-8000-<numero>.
-- Quedan 201 tutores de la carga en MAT1101, 134 en PRO1101, 132 en BDD1101,
-- 67 en ADM1101 y 66 en ING1101. Tarifas de 0 a 8.000, en pasos de 1.000.
WITH pares (carrera, par, k, asignatura) AS (VALUES
    -- ING-INFO (1) y ANA-PROG (2), malla 2024: MAT1101 (1) y PRO1101 (5);
    -- MAT1101 y BDD1101 (6); PRO1101 y BDD1101.
    (1, 0, 0, 1), (1, 0, 1, 5), (1, 1, 0, 1), (1, 1, 1, 6), (1, 2, 0, 5), (1, 2, 1, 6),
    (2, 0, 0, 1), (2, 0, 1, 5), (2, 1, 0, 1), (2, 1, 1, 6), (2, 2, 0, 5), (2, 2, 1, 6),
    -- ING-ADM (3), malla 2023: MAT1101 y ADM1101 (15); MAT1101 e ING1101 (2);
    -- ADM1101 e ING1101.
    (3, 0, 0, 1), (3, 0, 1, 15), (3, 1, 0, 1), (3, 1, 1, 2), (3, 2, 0, 15), (3, 2, 1, 2)
)
INSERT INTO perfil_tutor (id, usuario_id, asignatura_id, tarifa, descripcion, activo, creado_en, actualizado_en)
SELECT
    ('c1000000-0000-4000-8000-' || lpad(((c.n - 1) * 2 + p.k + 1)::text, 12, '0'))::uuid,
    c.usuario_id,
    ('40000000-0000-4000-8000-' || lpad(p.asignatura::text, 12, '0'))::uuid,
    ((c.n + 4 * p.k) % 9) * 1000,
    'Tutor de la carga de prueba (HU-34).',
    true,
    now(),
    now()
FROM carga AS c
JOIN pares AS p ON p.carrera = (c.n - 1) % 3 + 1 AND p.par = ((c.n - 1) / 3) % 3
WHERE c.n <= 300
ORDER BY c.n, p.k;

-- Tres bloques LIBRES de una hora por tutor, en dias distintos para que no se
-- crucen (ex_bloque_sin_solape): los dias 7, 9 y 11 despues de la carga, o
-- 8, 10 y 12, y en cada uno una hora entre las 12:00 y las 21:00 UTC (de 9:00
-- a 18:00 en hora de Chile, con UTC-3). Como los bloques futuros de los datos
-- de ejemplo, date_trunc('day', now(), 'UTC') es el dia de la carga a las
-- 00:00 UTC.
INSERT INTO bloque_disponibilidad (id, usuario_id, inicio_en, fin_en, estado, creado_en, actualizado_en)
SELECT
    ('c2000000-0000-4000-8000-' || lpad(((c.n - 1) * 3 + j + 1)::text, 12, '0'))::uuid,
    c.usuario_id,
    date_trunc('day', now(), 'UTC') + make_interval(days => 7 + 2 * j + c.n % 2, hours => 12 + c.n % 10),
    date_trunc('day', now(), 'UTC') + make_interval(days => 7 + 2 * j + c.n % 2, hours => 13 + c.n % 10),
    'LIBRE',
    now(),
    now()
FROM carga AS c
CROSS JOIN generate_series(0, 2) AS j
WHERE c.n <= 300
ORDER BY c.n, j;

COMMIT;

-- Resumen de lo cargado: las filas de la carga en cada tabla...
SELECT 'usuario_ref' AS tabla, count(*) AS filas FROM usuario_ref WHERE usuario_id IN (SELECT usuario_id FROM carga)
UNION ALL SELECT 'perfil_tutor' AS tabla, count(*) AS filas FROM perfil_tutor WHERE usuario_id IN (SELECT usuario_id FROM carga)
UNION ALL SELECT 'bloque_disponibilidad' AS tabla, count(*) AS filas FROM bloque_disponibilidad WHERE usuario_id IN (SELECT usuario_id FROM carga);

-- ...y los tutores de la carga en cada asignatura.
SELECT a.sigla, count(*) AS tutores_de_la_carga
FROM perfil_tutor AS p
JOIN asignatura_ref AS a ON a.asignatura_id = p.asignatura_id
WHERE p.usuario_id IN (SELECT usuario_id FROM carga) AND p.activo
GROUP BY a.sigla
ORDER BY tutores_de_la_carga DESC, a.sigla;
