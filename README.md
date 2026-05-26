# OLP Dashboard

Este proyecto convierte el script de reporte OLP en una plataforma Dockerizada con backend FastAPI y microservicios para ingestion y dashboard.

## Estructura

- `api/`: servicio FastAPI con endpoints y dashboard Jinja2
- `Dockerfile`: imagen Python y Uvicorn
- `docker-compose.yml`: servicios `web`, `db`, `redis`, `worker`, `beat`
- `requirements.txt`: dependencias Python
- `scripts/`: utilidades de instalación y seed
- `olp_report.py`: script legacy de generación de reporte

## Configuración

1. Crear el secreto de Confluence/Jira:
   ```powershell
   mkdir secrets
   Set-Content -Path .\secrets\atlassian_token.txt -Value "<tu_token>"
   ```
2. Levantar servicios:
   ```powershell
   docker compose up --build -d
   ```
3. Inicializar tablas PostgreSQL:
   ```powershell
   docker compose run --rm web python -c "from api.db import init_db; init_db()"
   ```
4. Sincronizar un proyecto OLP:
   ```powershell
   docker compose run --rm web python -m api.seed --project-key OLP --board-id 2
   ```

## Tareas en background

Se incluyó Celery con Redis. Servicios añadidos en `docker-compose.yml`: `redis`, `worker`, `beat`.

Para forzar la sincronización de todos los proyectos desde la API:

```powershell
curl -X POST http://localhost:8000/api/sync/
```

## API

- `GET /api/projects/`
- `GET /api/projects/{project_key}/metrics/`
- `POST /api/projects/{project_key}/sync/`
- `POST /api/sync/`
- `GET /dashboard/`
- `GET /docs`

## Notas

- Usa variables de entorno para `ATLASSIAN_SITE`, `ATLASSIAN_EMAIL` y `ATLASSIAN_TOKEN_FILE`.
- El frontend está servido desde FastAPI con Jinja2 en `api/templates/dashboard.html`.
- El servicio de sincronización programado se ejecuta diariamente con Celery Beat.
