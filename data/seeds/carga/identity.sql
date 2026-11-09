-- Carga de prueba FICTICIA para identity_db: 500 usuarios (HU-34, RNF-02).
-- Ninguna persona es real: los correos son carga.001@duocuc.cl a
-- carga.500@duocuc.cl y la clave de todas las cuentas es Tutorias2026.
-- Los identificadores son los mismos en identity_db y tutoring_db:
-- c0000000-0000-4000-8000-<el numero con 12 digitos>, del 1 al 500. Ningun
-- identificador de los datos de ejemplo empieza con c.
-- Va despues de los datos de ejemplo: usa sus carreras y sus sedes. Volver a
-- cargar los datos de ejemplo borra esta carga.
-- Se puede ejecutar las veces que haga falta: borra la carga anterior, y solo
-- esa, y la vuelve a crear.
-- Uso: .\scripts\cargar_usuarios_prueba.ps1  (o sh scripts/cargar_usuarios_prueba.sh).
--
-- El reparto, para el usuario numero n (de 1 a 500):
-- - carrera: la numero ((n - 1) mod 3) + 1 de los datos de ejemplo,
--   ING-INFO, ANA-PROG o ING-ADM;
-- - sede: la numero ((n - 1) mod 11) + 1 de los datos de ejemplo;
-- - del 1 al 300 son tutores, con nivel de 2 a 8 (RN-01: sus asignaturas son
--   del semestre 1, ver tutoring.sql); del 301 al 500, estudiantes, con nivel
--   de 1 a 8;
-- - nombre y apellido, de 20 nombres y 25 apellidos comunes en Chile: el
--   nombre cambia con cada usuario y el apellido cada 20, asi que ninguna
--   combinacion se repite. tutoring.sql usa las mismas listas.

\set ON_ERROR_STOP on
BEGIN;

-- Los 500 usuarios de la carga, con su numero.
CREATE TEMP TABLE carga AS
SELECT n, ('c0000000-0000-4000-8000-' || lpad(n::text, 12, '0'))::uuid AS id
FROM generate_series(1, 500) AS n;

-- Primero la carga anterior, y solo esa. Las filas hijas van antes que el
-- usuario: el borrado en cascada lo hace Django, no la base (anexo A, seccion 10).
DELETE FROM aviso_correo WHERE usuario_id IN (SELECT id FROM carga);
DELETE FROM refresh_token WHERE usuario_id IN (SELECT id FROM carga);
DELETE FROM token_verificacion WHERE usuario_id IN (SELECT id FROM carga);
DELETE FROM usuario WHERE id IN (SELECT id FROM carga);

-- Cuentas verificadas y activas, sin administrador. El hash es el de
-- valentina.demo en data/seeds/demo/identity.sql: la clave es Tutorias2026.
INSERT INTO usuario (id, email, password_hash, nombre, apellido, carrera_id, nivel, sede_id, email_verificado, activo, es_admin, creado_en, actualizado_en)
SELECT
    c.id,
    'carga.' || lpad(c.n::text, 3, '0') || '@duocuc.cl',
    'pbkdf2_sha256$1000000$DHFVSsuPss05MktqvbFNYB$gL1OvDnpy8cW+T+4wby/V5Z68IkPJLJJeP53LP/Ik/Y=',
    (ARRAY['Sofía', 'Martina', 'Isidora', 'Florencia', 'Agustina', 'Catalina', 'Antonia', 'Emilia', 'Trinidad', 'Javiera',
           'Benjamín', 'Vicente', 'Martín', 'Joaquín', 'Agustín', 'Cristóbal', 'Maximiliano', 'Lucas', 'Sebastián', 'Felipe'])[(c.n - 1) % 20 + 1],
    (ARRAY['González', 'Muñoz', 'Díaz', 'Pérez', 'Silva', 'Contreras', 'López', 'Martínez', 'Sepúlveda', 'Torres',
           'Araya', 'Flores', 'Espinoza', 'Valenzuela', 'Castillo', 'Ramírez', 'Reyes', 'Gutiérrez', 'Álvarez', 'Vásquez',
           'Tapia', 'Sánchez', 'Fernández', 'Carrasco', 'Cortés'])[(c.n - 1) / 20 + 1],
    ('20000000-0000-4000-8000-' || lpad(((c.n - 1) % 3 + 1)::text, 12, '0'))::uuid,
    CASE WHEN c.n <= 300 THEN 2 + (c.n - 1) % 7 ELSE 1 + (c.n - 1) % 8 END,
    ('30000000-0000-4000-8000-' || lpad(((c.n - 1) % 11 + 1)::text, 12, '0'))::uuid,
    true,
    true,
    false,
    now(),
    now()
FROM carga AS c
ORDER BY c.n;

COMMIT;

-- Resumen de lo cargado
SELECT (SELECT count(*) FROM usuario WHERE id IN (SELECT id FROM carga)) AS cuentas_de_la_carga,
       (SELECT count(*) FROM usuario) AS cuentas_en_total;
