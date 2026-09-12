const express = require('express');
const cors = require('cors');
const path = require('path');
require('dotenv').config();

const db = require('./config/db'); // Tu conexión a MySQL

const app = express();
const PORT = process.env.PORT || 3306;

// Middlewares
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Servir archivos estáticos del frontend desde la raíz del proyecto
app.use(express.static(__dirname));

// Ruta raíz: redirige automáticamente a asignaturas.html
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'asignaturas.html'));
});

// ENDPOINT: Obtener asignaturas filtradas desde MySQL
app.get('/api/asignaturas', async (req, res) => {
  try {
    const { nombre, area } = req.query;
    let sql = 'SELECT * FROM asignatura WHERE 1=1';
    const params = [];

    if (nombre && nombre.trim() !== '') {
      sql += ' AND (nombre LIKE ? OR codigo LIKE ?)';
      params.push(`%${nombre.trim()}%`, `%${nombre.trim()}%`);
    }

    if (area && area.trim() !== '') {
      sql += ' AND area = ?';
      params.push(area.trim());
    }

    sql += ' ORDER BY nombre ASC';

    const [rows] = await db.query(sql, params);
    res.json(rows);
  } catch (err) {
    console.error('Error SQL en /api/asignaturas:', err);
    res.status(500).json({ error: 'Error al consultar la base de datos' });
  }
});

// ENDPOINT: Obtener la lista de Áreas únicas
app.get('/api/areas', async (req, res) => {
  try {
    const [rows] = await db.query('SELECT DISTINCT area FROM asignatura WHERE area IS NOT NULL AND area != "" ORDER BY area ASC');
    res.json(rows.map(r => r.area));
  } catch (err) {
    console.error('Error SQL en /api/areas:', err);
    res.json([]);
  }
});

// ENDPOINT DE PRUEBA
app.get('/api/test', (req, res) => {
  res.json({ mensaje: '¡Servidor y Base de Datos funcionando perfectamente!' });
});

// Iniciar servidor en el puerto 3000
const SERVER_PORT = 3000;
app.listen(SERVER_PORT, () => {
  console.log(`🚀 Servidor ejecutándose en http://localhost:${SERVER_PORT}`);
});