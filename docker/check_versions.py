"""Check the installed stack without starting an EnergyPlus simulation."""

import platform
import re
import subprocess
import sys
from importlib.metadata import version

import gymnasium
import ipykernel
import numpy as np
import sinergym
import stable_baselines3
import torch
from pyenergyplus.api import EnergyPlusAPI

if sys.version_info[:2] != (3, 12) or platform.machine() != "x86_64":
    raise SystemExit(f"Unexpected platform: Python {platform.python_version()}, {platform.machine()}")

print(f"Python {platform.python_version()} ({platform.machine()})")
for name, expected in {
    "sinergym": "3.12.2",
    "gymnasium": "1.2.3",
    "stable-baselines3": "2.7.1",
    "torch": "2.9.1+cpu",
    "ipykernel": "6.30.1",
}.items():
    actual = version(name)
    if actual != expected:
        raise SystemExit(f"{name}: expected {expected}, got {actual}")
    print(f"{name} {actual}")

if torch.version.cuda is not None or torch.version.hip is not None:
    raise SystemExit("Expected a CPU-only PyTorch build")
if torch.from_numpy(np.array([1.0])).numpy().item() != 1.0:
    raise SystemExit("NumPy/PyTorch conversion failed")

energyplus_version = subprocess.check_output(["energyplus", "--version"], text=True).strip()
if not re.search(r"\b25\.1\.0-1c11a3d85f\b", energyplus_version):
    raise SystemExit(f"Unexpected EnergyPlus version: {energyplus_version}")
print(energyplus_version)
print(f"EnergyPlus API {EnergyPlusAPI().api_version()}")
