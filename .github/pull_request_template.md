## Que hace

HU-nn - Una frase con lo que entrega la historia.

## Como probarlo

1. `Copy-Item .env.example .env`
2. `docker compose up -d --build`
3. ...

## Marcar lo que corresponda

- [ ] Pruebas nuevas o actualizadas
- [ ] Contrato de `docs/api` actualizado si cambio la API
- [ ] Migracion incluida y probada sobre base vacia
- [ ] Las variables nuevas estan en `.env.example`
- [ ] No hay claves ni datos reales en el cambio

## Quien debe aprobar

Infraestructura, contratos congelados o seguridad: Bryan, obligatorio.
Si Bryan es el autor, aprueba su segundo: Francisco en infraestructura y
canal de integracion, Damaris en Identidad y Pagos.
