document.addEventListener('DOMContentLoaded', () => {
    cargarAreas();
    cargarAsignaturas();
    configurarBuscador();
});

let timeoutId;
let paginaActual = 1;
const LIMITE_POR_PAGINA = 48;

function configurarBuscador() {
    const searchInput = document.getElementById('subjectSearch');
    if (searchInput) {
        // Búsqueda mientras escribe (con debounce de 300ms)
        searchInput.addEventListener('input', () => {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => {
                paginaActual = 1;
                cargarAsignaturas();
            }, 300);
        });

        // Búsqueda al presionar Enter
        searchInput.addEventListener('keyup', (e) => {
            if (e.key === 'Enter') {
                clearTimeout(timeoutId);
                paginaActual = 1;
                cargarAsignaturas();
            }
        });
    }

    const areaSelect = document.getElementById('filter-area');
    if (areaSelect) {
        areaSelect.addEventListener('change', () => {
            paginaActual = 1;
            cargarAsignaturas();
        });
    }
}

// 1. Cargar selector de Áreas desde la BD
async function cargarAreas() {
    try {
        let areas = [];
        const res = await fetch('/api/catalog/v1/areas');
        if (res.ok) {
            areas = await res.json();
        } else {
            // Fallback por carreras si áreas aún no está disponible
            const resCarreras = await fetch('/api/catalog/v1/carreras');
            const carreras = await resCarreras.json();
            areas = [...new Set(carreras.map(c => c.escuela))].sort();
        }

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

// 2. Cargar y renderizar Cards desde la BD con Paginación
async function cargarAsignaturas() {
    const contenedor = document.getElementById('subjectsList');
    const counter = document.getElementById('subjectCounter');
    const noResults = document.getElementById('noResults');
    const paginationContainer = document.getElementById('paginationContainer');

    const searchInput = document.getElementById('subjectSearch');
    const areaSelect = document.getElementById('filter-area');

    const texto = searchInput ? searchInput.value.trim() : '';
    const area = areaSelect ? areaSelect.value.trim() : '';

    const params = new URLSearchParams();
    if (texto) params.append('buscar', texto);
    if (area) params.append('area', area);
    params.append('pagina', paginaActual);
    params.append('limite', LIMITE_POR_PAGINA);
    params.append('paginado', '1');

    try {
        const response = await fetch(`/api/catalog/v1/asignaturas?${params.toString()}`);
        const data = await response.json();

        // Soporta tanto formato paginado como lista directa
        const esPaginado = !Array.isArray(data) && data.resultados !== undefined;
        const asignaturas = esPaginado ? data.resultados : data;
        const total = esPaginado ? data.total : asignaturas.length;
        const totalPaginas = esPaginado ? data.total_paginas : Math.ceil(total / LIMITE_POR_PAGINA);

        // Actualizar el contador
        if (counter) {
            if (total === 0) {
                counter.textContent = '0 asignaturas encontradas';
            } else if (totalPaginas > 1) {
                counter.textContent = `${total} asignaturas encontradas (Página ${paginaActual} de ${totalPaginas})`;
            } else {
                counter.textContent = `${total} ${total === 1 ? 'asignatura encontrada' : 'asignaturas encontradas'}`;
            }
        }

        // Mostrar u ocultar mensaje de "Sin resultados"
        if (asignaturas.length === 0) {
            contenedor.innerHTML = '';
            if (noResults) noResults.style.display = 'block';
            if (paginationContainer) paginationContainer.innerHTML = '';
            return;
        }

        if (noResults) noResults.style.display = 'none';

        // Renderizar las Cards en la Grilla
        contenedor.innerHTML = asignaturas.map(asig => {
            const idSubject = asig.id || '';
            const areaTexto = asig.area || (asig.creditos ? asig.creditos + ' créditos' : 'Duoc UC');

            return `
                <article class="subject-card">
                    <div>
                        <div class="subject-card-header">
                            <div class="subject-icon">
                                <i class="fa-solid fa-book"></i>
                            </div>
                            <span class="subject-code">${asig.sigla || 'ASIG'}</span>
                        </div>

                        <h3>${asig.nombre}</h3>
                        <p class="subject-area">${areaTexto}</p>
                    </div>

                    <div class="subject-card-footer">
                        <span class="tutor-count">
                            <i class="fa-solid fa-user-graduate"></i>
                            Ver disponibilidad
                        </span>
                        <button class="view-tutors" onclick="verTutores('${idSubject}')">
                            Ver tutores →
                        </button>
                    </div>
                </article>
            `;
        }).join('');


        // Renderizar controles de paginación
        renderizarPaginacion(totalPaginas);

    } catch (error) {
        console.error('Error al cargar las cards:', error);
        if (contenedor) {
            contenedor.innerHTML = '<p style="color:red; grid-column: 1/-1; text-align:center;">Error al conectar con la base de datos.</p>';
        }
    }
}

// 3. Renderizar botones de paginación
function renderizarPaginacion(totalPaginas) {
    const container = document.getElementById('paginationContainer');
    if (!container) return;

    if (totalPaginas <= 1) {
        container.innerHTML = '';
        return;
    }

    let html = '';

    // Botón Anterior
    const anteriorDisabled = paginaActual === 1 ? 'disabled' : '';
    html += `<button class="pagination-btn" ${anteriorDisabled} onclick="cambiarPagina(${paginaActual - 1})"><i class="fa-solid fa-chevron-left"></i> Anterior</button>`;

    // Números de página inteligentes
    const rangoVisible = 2; // Cantidad de páginas alrededor de la actual
    let paginasAMostrar = [];

    for (let p = 1; p <= totalPaginas; p++) {
        if (
            p === 1 || 
            p === totalPaginas || 
            (p >= paginaActual - rangoVisible && p <= paginaActual + rangoVisible)
        ) {
            paginasAMostrar.push(p);
        }
    }

    let ultimaPagina = 0;
    paginasAMostrar.forEach(p => {
        if (ultimaPagina > 0 && p - ultimaPagina > 1) {
            html += `<span class="pagination-ellipsis">...</span>`;
        }
        const activeClass = p === paginaActual ? 'active' : '';
        html += `<button class="pagination-btn ${activeClass}" onclick="cambiarPagina(${p})">${p}</button>`;
        ultimaPagina = p;
    });

    // Botón Siguiente
    const siguienteDisabled = paginaActual === totalPaginas ? 'disabled' : '';
    html += `<button class="pagination-btn ${siguienteDisabled} onclick="cambiarPagina(${paginaActual + 1})">Siguiente <i class="fa-solid fa-chevron-right"></i></button>`;

    container.innerHTML = html;
}

// 4. Cambiar de página
function cambiarPagina(nuevaPagina) {
    paginaActual = nuevaPagina;
    cargarAsignaturas();
    const section = document.querySelector('.subjects-results-header');
    if (section) {
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function verTutores(idAsignatura) {
    window.location.href = `tutores.html?asignatura=${idAsignatura}`;
}

window.cambiarPagina = cambiarPagina;
window.verTutores = verTutores;