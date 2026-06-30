#!/usr/bin/env python3
import os
import sys
import signal

def kill_zombies_on_ports(ports):
    # Convert ports to hex format in uppercase (as represented in /proc/net/tcp)
    port_hexes = {f"{port:04X}" for port in ports}
    inodes = set()

    # Read listening sockets from /proc/net/tcp and /proc/net/tcp6
    for path in ["/proc/net/tcp", "/proc/net/tcp6"]:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r") as f:
                lines = f.readlines()
            for line in lines[1:]:
                parts = line.strip().split()
                if len(parts) < 10:
                    continue
                local_addr = parts[1]
                state = parts[3]
                inode = parts[9]
                if ":" in local_addr:
                    local_port = local_addr.split(":")[1].upper()
                    # state "0A" is TCP_LISTEN
                    if local_port in port_hexes and state == "0A":
                        inodes.add(inode)
        except Exception as e:
            print(f"Warning: failed to read {path}: {e}", file=sys.stderr)

    if not inodes:
        print("No zombie socket inodes found listening on ports:", sorted(list(ports)))
        return

    print(f"Found socket inodes on target ports: {inodes}")

    my_pid = os.getpid()
    killed_any = False

    # Scan all processes in /proc to find who owns these socket inodes
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        if pid == my_pid:
            continue
        fd_dir = f"/proc/{name}/fd"
        if not os.path.exists(fd_dir):
            continue
        try:
            for fd in os.listdir(fd_dir):
                fd_path = os.path.join(fd_dir, fd)
                try:
                    target = os.readlink(fd_path)
                    if target.startswith("socket:[") and target.endswith("]"):
                        inode = target[8:-1]
                        if inode in inodes:
                            print(f"Killing zombie process with PID {pid} owning socket {target}...")
                            try:
                                os.kill(pid, signal.SIGKILL)
                                killed_any = True
                            except ProcessLookupError:
                                pass
                            except PermissionError as e:
                                print(f"Warning: insufficient permissions to kill PID {pid}: {e}", file=sys.stderr)
                            break
                except Exception:
                    pass
        except Exception:
            pass

    if not killed_any:
        print("No zombie processes found owning those sockets.")

if __name__ == "__main__":
    target_ports = {50051, 50052, 50060}
    kill_zombies_on_ports(target_ports)
