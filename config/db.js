const mysql = require('mysql2/promise');

// Configuración directa con los datos reales de tu MySQL Workbench
const pool = mysql.createPool({
  host: '127.0.0.1',                  // Forzamos IP TCP/IP para evitar socket unix en macOS
  user: 'root',                       // Tu usuario que se ve en la captura
  password: 'Misaka#9982',            // Tu contraseña
  database: 'plataforma_tutorias',   // El nombre exacto de tu base de datos de la captura
  port: 3306,
  waitForConnections: true,
  connectionLimit: 10,
  queueLimit: 0
});

// Prueba de conexión inmediata
(async () => {
  try {
    const connection = await pool.getConnection();
    console.log('✅ CONEXIÓN EXITOSA a la base de datos: plataforma_tutorias');
    
    // Probar si lee la tabla asignatura
    const [rows] = await connection.query('SELECT COUNT(*) as total FROM asignatura');
    console.log(`📚 Asignaturas encontradas en la BD: ${rows[0].total}`);
    
    connection.release();
  } catch (err) {
    console.error('❌ Error de conexión:', err.message);
  }
})();

module.exports = pool;