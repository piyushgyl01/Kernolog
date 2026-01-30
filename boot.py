import subprocess
import sys
import shutil
import time
import os

def spawn_terminal(script_name):
    """Launch a script in a new terminal window."""
    terminals = [('gnome-terminal', ['--']), ('xfce4-terminal', ['-e']), ('xterm', ['-e']), ('terminator', ['-x'])]
    for term, args in terminals:
        if shutil.which(term):
            cmd = [term] + args + [sys.executable, script_name]
            return subprocess.Popen(cmd)
    return None

def main():
    print("🟢 Booting Kernolog Microlith...")

    # 1. Start the Engine
    engine_process = subprocess.Popen([sys.executable, "engine.py"])
    print(f"   [PID {engine_process.pid}] Engine Started.")
    
    time.sleep(2) # Wait for engine init

    # 2. Spawn the Shell
    shell_process = spawn_terminal("shell.py")
    
    if shell_process:
        print(f"   [PID {shell_process.pid}] Shell Launched in new window.")
        print("\nPress Ctrl+C here to stop all services.")
    else:
        print("⚠️  Could not launch terminal. Open a new window and run 'python shell.py'")

    try:
        engine_process.wait()
    except KeyboardInterrupt:
        print("\n🔴 Shutting down...")
        engine_process.terminate()
        if shell_process: shell_process.terminate()
        print("Bye.")

if __name__ == "__main__":
    main()