#!/usr/bin/env python3
"""
chat_client.py - Interactive TCP Terminal Client
"""

import socket
import threading
import json
import struct
import sys
import time

def send_frame(sock: socket.socket, data: dict):
    payload = json.dumps(data).encode('utf-8')
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def receive_frame(sock: socket.socket) -> dict:
    header = sock.recv(4)
    if not header or len(header) < 4:
        return None
    length = struct.unpack("!I", header)[0]
    buf = bytearray()
    while len(buf) < length:
        chunk = sock.recv(min(length - len(buf), 4096))
        if not chunk:
            return None
        buf.extend(chunk)
    return json.loads(buf.decode('utf-8'))


def receiver_loop(sock: socket.socket, shutdown_flag: threading.Event):
    while not shutdown_flag.is_set():
        try:
            msg = receive_frame(sock)
            if msg is None:
                print("\n[Disconnected from server]")
                shutdown_flag.set()
                break

            mtype = msg.get("type")
            if mtype == "chat":
                print(f"\n[{msg['room']}] {msg['from']}: {msg['content']}\n> ", end="", flush=True)
            elif mtype == "private":
                print(f"\n[PRIVATE from {msg['from']}]: {msg['content']}\n> ", end="", flush=True)
            elif mtype == "system":
                print(f"\n*** SYSTEM: {msg['content']} ***\n> ", end="", flush=True)
            else:
                body = msg.get("message") or msg.get("rooms") or msg.get("users")
                print(f"\n[{msg.get('status', 'INFO').upper()}]: {body}\n> ", end="", flush=True)
        except Exception:
            break


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <server_ip> <username>")
        return

    srv_ip = sys.argv[1]
    username = sys.argv[2]
    port = 9000

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((srv_ip, port))
    except Exception as e:
        print(f"Connection failed to {srv_ip}:{port} -> {e}")
        return

    # Handshake & Registration
    send_frame(sock, {"action": "register", "username": username})
    resp = receive_frame(sock)
    if not resp or resp.get("status") != "ok":
        print(f"Registration rejected: {resp}")
        sock.close()
        return

    print(f"Joined chat as '{username}'. Default channel: #general")
    print("Commands:")
    print("  /join <#room>        Join #general, #vip, or #emergency")
    print("  /msg <user> <text>   Send a direct message")
    print("  /rooms               Show available rooms")
    print("  /users               Show online users")
    print("  /quit                Exit chat")
    print("  <any text>           Send message to current room\n")

    shutdown_flag = threading.Event()
    t = threading.Thread(target=receiver_loop, args=(sock, shutdown_flag), daemon=True)
    t.start()

    try:
        while not shutdown_flag.is_set():
            cmd = input("> ").strip()
            if not cmd:
                continue

            if cmd == "/quit":
                break
            elif cmd.startswith("/join "):
                room_target = cmd.split(" ", 1)[1].strip()
                send_frame(sock, {"action": "join_room", "room": room_target})
            elif cmd.startswith("/msg "):
                parts = cmd.split(" ", 2)
                if len(parts) >= 3:
                    send_frame(sock, {"action": "private_msg", "to": parts[1], "message": parts[2]})
                else:
                    print("Usage: /msg <user> <message>")
            elif cmd == "/rooms":
                send_frame(sock, {"action": "list_rooms"})
            elif cmd == "/users":
                send_frame(sock, {"action": "list_users"})
            else:
                send_frame(sock, {"action": "chat", "message": cmd})

            time.sleep(0.02)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        shutdown_flag.set()
        sock.close()
        print("\nExited.")


if __name__ == '__main__':
    main()