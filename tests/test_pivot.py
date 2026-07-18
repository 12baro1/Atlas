import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pivot import Pivot

p=Pivot(
    index=10,
    price=65230.5,
    kind="HIGH"
)

print()

print(p)

