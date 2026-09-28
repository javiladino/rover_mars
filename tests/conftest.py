"""
Configuración compartida de pytest.

Añade al PYTHONPATH los módulos que se testean pero que no son paquetes
instalables (viven dentro de airflow/plugins y simulator/), para poder
hacer `import calibration` o `import ccsds_encoder` directamente desde
tests/ sin necesidad de instalar el proyecto.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

for module_dir in ("airflow/plugins", "simulator", "common"):
    path = str(ROOT / module_dir)
    if path not in sys.path:
        sys.path.insert(0, path)
