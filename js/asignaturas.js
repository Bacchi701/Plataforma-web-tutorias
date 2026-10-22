document.addEventListener('DOMContentLoaded', () => {
    cargarAreas();
    cargarAsignaturas();
    configurarBuscador();
});

let timeoutId;

function configurarBuscador() {
    const searchInput = document.getElementById('subjectSearch');
    if (searchInput) {
        // Búsqueda mientras escribe (con debounce de 300ms)
        searchInput.addEventListener('input', () => {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => {
                cargarAsignaturas();
            }, 300);
        });

        // Búsqueda al presionar Enter
        searchInput.addEventListener('keyup', (e) => {
            if (e.key === 'Enter') {
                clearTimeout(timeoutId);
                cargarAsignaturas();
            }
        });
    }
}

// 1. Cargar selector de Áreas desde la BD
async function cargarAreas() {
    try {
        const res = await fetch('/api/areas');
        const areas = await res.json();
        const selectArea = document.getElementById('filter-area');

        if (selectArea) {
            selectArea.innerHTML = '<option value="">Todas las Áreas</option>';
            areas.forEach(area => {
                const option = document.createElement('option');
                option.value = area;
                option.textContent = area;
                selectArea.appendChild(option);
            });
        }
    } catch (err) {
        console.error('Error al cargar las áreas:', err);
    }
}

// 2. Cargar y renderizar Cards desde la BD
async function cargarAsignaturas() {
    const contenedor = document.getElementById('subjectsList');
    const counter = document.getElementById('subjectCounter');
    const noResults = document.getElementById('noResults');

    const searchInput = document.getElementById('subjectSearch');
    const areaSelect = document.getElementById('filter-area');

    const nombre = searchInput ? searchInput.value.trim() : '';
    const area = areaSelect ? areaSelect.value : '';

    const params = new URLSearchParams();
    if (nombre) params.append('nombre', nombre);
    if (area) params.append('area', area);

    try {
        const response = await fetch(`/api/asignaturas?${params.toString()}`);
        const asignaturas = await response.json();

        // Actualizar el contador
        const total = asignaturas.length;
        if (counter) {
            counter.textContent = `${total} ${total === 1 ? 'asignatura encontrada' : 'asignaturas encontradas'}`;
        }

        // Mostrar u ocultar mensaje de "Sin resultados"
        if (total === 0) {
            contenedor.innerHTML = '';
            if (noResults) noResults.style.display = 'block';
            return;
        }

        if (noResults) noResults.style.display = 'none';

        // Renderizar las Cards en la Grilla
        contenedor.innerHTML = asignaturas.map(asig => {
            const idSubject = asig.id_asignatura || asig.id || '';
            
            return `
                <article class="subject-card" data-area="${asig.area || ''}">
                    <div>
                        <div class="subject-card-header">
                            <div class="subject-icon">
                                <i class="fa-solid fa-book"></i>
                            </div>
                            <span class="subject-code">${asig.codigo || 'ASIG'}</span>
                        </div>

                        <h3>${asig.nombre}</h3>
                        <p class="subject-area">${asig.carrera || asig.area || 'Escuela Duoc UC'}</p>
                    </div>

                    <div class="subject-card-footer">
                        <span class="tutor-count">
                            <i class="fa-solid fa-user-graduate"></i>
                            ${asig.tutores_count || 0} tutores
                        </span>
                        <button class="view-tutors" onclick="verTutores('${idSubject}')">
                            Ver tutores →
                        </button>
                    </div>
                </article>
            `;
        }).join('');

    } catch (error) {
        console.error('Error al cargar las cards:', error);
        if (contenedor) {
            contenedor.innerHTML = '<p style="color:red; grid-column: 1/-1; text-align:center;">Error al conectar con la base de datos.</p>';
        }
    }
}

function verTutores(idAsignatura) {
    window.location.href = `tutores.html?asignatura=${idAsignatura}`;
}