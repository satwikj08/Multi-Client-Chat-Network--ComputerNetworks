#!/usr/bin/env python3
"""
chat_server.py - Low-level Multi-Threaded TCP Chat Server with SDN REST Hook
"""

import socket
import threading
import json
import struct
import requests
import time
import sys

LISTEN_HOST = '0.0.0.0'
LISTEN_PORT = 9000
SDN_REST_ENDPOINT = 'http://127.0.0.1:8080'

# In-memory synchronization structures
state_lock = threading.Lock()
# username -> {"sock": sock, "ip": ip, "port": port, "room": room}
connected_clients = {}
# socket -> username
sock_to_user = {}
# room -> set of usernames
chat_rooms = {
    "#general": set(),
    "#vip": set(),
    "#emergency": set()
}

# Spam rate limit parameters
RATE_LIMIT_COUNT = 8
RATE_LIMIT_WINDOW = 2.0
user_message_log = {}


def send_frame(sock: socket.socket, payload_dict: dict):
    data = json.dumps(payload_dict).encode('utf-8')
    frame = struct.pack("!I", len(data)) + data
    sock.sendall(frame)


def read_frame(sock: socket.socket) -> dict:
    header = sock.recv(4)
    if not header or len(header) < 4:
        return None
    length = struct.unpack("!I", header)[0]
    
    received_bytes = bytearray()
    while len(received_bytes) < length:
        chunk = sock.recv(min(length - len(received_bytes), 4096))
        if not chunk:
            return None
        received_bytes.extend(chunk)
    
    return json.loads(received_bytes.decode('utf-8'))


def notify_sdn_priority(client_ip: str, room_name: str):
    """Pushes a priority update to the Ryu SDN controller."""
    try:
        url = f"{SDN_REST_ENDPOINT}/chat/policy/prioritize"
        body = {
            "client_ip": client_ip,
            "room": room_name,
            "priority": 30000 if room_name == "#emergency" else 20000
        }
        res = requests.post(url, json=body, timeout=1.0)
        print(f"[SDN] Priority updated for {client_ip} ({room_name}) -> HTTP {res.status_code}")
    except Exception as err:
        print(f"[SDN-WARN] Could not reach SDN controller: {err}")


def notify_sdn_block(client_ip: str, duration: int = 30):
    """Triggers an OpenFlow DROP rule on the SDN controller."""
    try:
        url = f"{SDN_REST_ENDPOINT}/chat/policy/block"
        body = {"client_ip": client_ip, "duration": duration}
        res = requests.post(url, json=body, timeout=1.0)
        print(f"[SDN] Block request sent for {client_ip} -> HTTP {res.status_code}")
    except Exception as err:
        print(f"[SDN-WARN] Could not reach SDN controller: {err}")


def broadcast_room(room_name: str, payload: dict, exclude_sender: str = None):
    with state_lock:
        members = list(chat_rooms.get(room_name, set()))
    for user in members:
        if user == exclude_sender:
            continue
        with state_lock:
            client_info = connected_clients.get(user)
        if client_info:
            try:
                send_frame(client_info["sock"], payload)
            except Exception:
                pass


def send_direct_message(recipient: str, payload: dict) -> bool:
    with state_lock:
        info = connected_clients.get(recipient)
    if info:
        try:
            send_frame(info["sock"], payload)
            return True
        except Exception:
            return False
    return False


def is_rate_limited(username: str, client_ip: str) -> bool:
    now = time.time()
    history = user_message_log.setdefault(username, [])
    # Filter timestamps outside window
    history = [t for t in history if now - t < RATE_LIMIT_WINDOW]
    history.append(now)
    user_message_log[username] = history

    if len(history) > RATE_LIMIT_COUNT:
        print(f"[ALERT] Abuse detected from {username} ({client_ip}). Calling SDN Firewall...")
        notify_sdn_block(client_ip, duration=25)
        return True
    return False


def client_connection_handler(client_sock: socket.socket, addr: tuple):
    client_ip, client_port = addr
    current_user = None
    print(f"[*] New TCP connection established: {client_ip}:{client_port}")

    try:
        while True:
            msg = read_frame(client_sock)
            if msg is None:
                break

            action = msg.get("action")

            # 1. Registration
            if action == "register":
                req_user = msg.get("username", "").strip()
                with state_lock:
                    if not req_user or req_user in connected_clients:
                        send_frame(client_sock, {"status": "error", "message": "Username unavailable."})
                        continue

                    current_user = req_user
                    connected_clients[current_user] = {
                        "sock": client_sock,
                        "ip": client_ip,
                        "port": client_port,
                        "room": "#general"
                    }
                    sock_to_user[client_sock] = current_user
                    chat_rooms["#general"].add(current_user)

                send_frame(client_sock, {"status": "ok", "message": f"Registered as {current_user}. Default room: #general"})
                broadcast_room("#general", {"type": "system", "content": f"{current_user} entered #general."}, exclude_sender=current_user)

            elif not current_user:
                send_frame(client_sock, {"status": "error", "message": "Registration required."})
                continue

            # Spam & Flooding Check
            elif is_rate_limited(current_user, client_ip):
                send_frame(client_sock, {"status": "error", "message": "Spam detected. Blocked by SDN controller."})
                break

            # 2. Join Room
            elif action == "join_room":
                target_room = msg.get("room")
                with state_lock:
                    if target_room not in chat_rooms:
                        send_frame(client_sock, {"status": "error", "message": f"Room {target_room} not found."})
                        continue
                    prev_room = connected_clients[current_user]["room"]
                    chat_rooms[prev_room].discard(current_user)
                    chat_rooms[target_room].add(current_user)
                    connected_clients[current_user]["room"] = target_room

                broadcast_room(prev_room, {"type": "system", "content": f"{current_user} moved to {target_room}."})
                broadcast_room(target_room, {"type": "system", "content": f"{current_user} joined {target_room}."})
                send_frame(client_sock, {"status": "ok", "message": f"Switched to {target_room}."})

                # Dynamic SDN Priority Policy for VIP / Emergency rooms
                if target_room in ("#vip", "#emergency"):
                    notify_sdn_priority(client_ip, target_room)

            # 3. Room Chat Broadcast
            elif action == "chat":
                room = connected_clients[current_user]["room"]
                broadcast_room(room, {
                    "type": "chat",
                    "from": current_user,
                    "room": room,
                    "content": msg.get("message", ""),
                    "timestamp": time.time()
                })

            # 4. Private Messaging
            elif action == "private_msg":
                target = msg.get("to")
                delivered = send_direct_message(target, {
                    "type": "private",
                    "from": current_user,
                    "content": msg.get("message", ""),
                    "timestamp": time.time()
                })
                if delivered:
                    send_frame(client_sock, {"status": "ok", "message": f"Delivered to {target}."})
                else:
                    send_frame(client_sock, {"status": "error", "message": f"User {target} is offline."})

            # 5. Room and User Discovery
            elif action == "list_rooms":
                with state_lock:
                    snap = {r: list(m) for r, m in chat_rooms.items()}
                send_frame(client_sock, {"status": "ok", "rooms": snap})

            elif action == "list_users":
                with state_lock:
                    users = list(connected_clients.keys())
                send_frame(client_sock, {"status": "ok", "users": users})

    except (ConnectionResetError, BrokenPipeError, socket.error):
        pass
    finally:
        with state_lock:
            if current_user and current_user in connected_clients:
                user_room = connected_clients[current_user]["room"]
                chat_rooms[user_room].discard(current_user)
                del connected_clients[current_user]
            sock_to_user.pop(client_sock, None)
        client_sock.close()
        print(f"[-] Session terminated: {current_user or client_ip}")
        if current_user:
            broadcast_room(user_room, {"type": "system", "content": f"{current_user} has disconnected."})


def run_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, LISTEN_PORT))
    srv.listen(64)
    print(f"=== TCP Chat Server active on port {LISTEN_PORT} ===")

    try:
        while True:
            sock, addr = srv.accept()
            t = threading.Thread(target=client_connection_handler, args=(sock, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nShutting down server.")
    finally:
        srv.close()


if __name__ == '__main__':
    run_server()