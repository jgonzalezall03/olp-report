#!/bin/bash
# Ejecutar reporte OLP y publicar en Confluence
cd "$(dirname "$0")"
python3 olp_report.py --publish 2>&1
