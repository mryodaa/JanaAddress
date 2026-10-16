"""Обучение посимвольного теггера. Вне src: torch и прочие зависимости обучения в образ не попадают.

src добавляется в sys.path здесь, до импорта любого модуля training: признаки и рантайм теггера
(jana_address.tagger) общие для обучения и сервиса.
"""

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
