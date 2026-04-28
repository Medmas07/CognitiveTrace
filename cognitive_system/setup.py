#!/usr/bin/env python3
"""
Quick setup helper — creates Python venv and installs dependencies.
Run once before first use: python setup.py
"""
import subprocess, sys, os

VENV = os.path.join(os.path.dirname(__file__), ".venv")
REQ  = os.path.join(os.path.dirname(__file__), "system_agent", "requirements.txt")

def run(cmd):
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

print("=== Cognitive System Setup ===\n")

if not os.path.isdir(VENV):
    print("[1/2] Creating virtual environment...")
    run([sys.executable, "-m", "venv", VENV])
else:
    print("[1/2] Virtual environment already exists.")

pip = os.path.join(VENV, "Scripts", "pip") if os.name == "nt" else os.path.join(VENV, "bin", "pip")
print("[2/2] Installing dependencies...")
run([pip, "install", "--upgrade", "pip"])
run([pip, "install", "-r", REQ])

print("\nSetup complete.")
print("Launch the desktop application with:")
if os.name == "nt":
    print(f"  .venv\\Scripts\\python -m system_agent")
    print("  or double-click run_collector.pyw after dependencies are installed")
else:
    print(f"  .venv/bin/python -m system_agent")
print("\nThen load the browser_agent_v2/ folder as an unpacked Chrome extension.")
