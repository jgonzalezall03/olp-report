"""Registra todos los proyectos Jira en la DB y dispara sincronización."""
from api.db import init_db
from api.seed import create_project, sync_project
from api.services.jira_service import JiraClient

# projectKey -> (board_id, project_name, is_kanban)
PROJECTS = {
    "ADP":   (448,  "Automatización de Procesos",          True),
    "AI":    (14,   "Analitica Ilis",                       False),
    "AN":    (11,   "Analítica",                            True),
    "DCV":   (349,  "Docuvex",                              False),
    "DCX":   (1211, "Docuvex Kanban",                       True),
    "DT2":   (979,  "Docuvex Technical 2",                  True),
    "DTECH": (945,  "Docuvex Technical",                    True),
    "DTI":   (1,    "Dirección Tecnología e Informática",   True),
    "EN":    (1178, "Estandarización Nxtara",               True),
    "EXP":   (811,  "STRIDER AI",                           True),
    "IP":    (8,    "Xperium",                              False),
    "N2025": (316,  "Iniciativas y proyectos",              True),
    "NT":    (1012, "Gestión de Proyectos Internos Nxtara", True),
    "NXDAY": (1244, "Nxtara Day 2026",                      True),
    "OII":   (712,  "Orvix Internacional II",               False),
    "OLI":   (10,   "Olimpo Internacional",                 True),
    "OLP":   (2,    "Olimpo",                               False),
    "OP":    (16,   "Olimpo Puma",                          False),
    "PC":    (52,   "Proyecto Centralización",              True),
    "PCCD":  (151,  "Proyecto CAD-Chile (DATAERA)",         True),
    "PI":    (217,  "Portafolio Ilis",                      True),
    "RC":    (778,  "Release Coordination",                 True),
    "SAI":   (1145, "Strider AI",                           True),
    "SDMES": (415,  "Sistema de Monitoreo en Sucursales",   True),
    "SPG":   (382,  "Sistema Parámetros Generales",         True),
    "UA":    (283,  "UX/UI Asignaciones",                   True),
}

if __name__ == "__main__":
    init_db()
    for key, (board_id, name, is_kanban) in PROJECTS.items():
        print(f"[{key}] Registrando ({'Kanban' if is_kanban else 'Scrum'})...", flush=True)
        create_project(key, board_id, name, is_kanban=is_kanban)
        try:
            result = sync_project(key)
            print(f"[{key}] {result}", flush=True)
        except Exception as e:
            print(f"[{key}] ERROR: {e}", flush=True)
