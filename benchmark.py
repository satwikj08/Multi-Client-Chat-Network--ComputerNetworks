#!/usr/bin/env python3
"""
benchmark.py - Evaluates latency, concurrency, and flow table modifications
"""

import socket
import struct
import json
import time
import threading
import statistics
import sys
import subprocess

TARGET_IP = '10.0.0.100'
TARGET_PORT = 9000

def pack(d):
    raw = json.dumps(d).encode('utf-8')
    return struct.pack("!I", len(raw)) + raw

def unpack(s):
    h = s.recv(4)
    if not h: return None
    length = struct.unpack("!I", h)[0]
    b = bytearray()
    while len(b) < length:
        c = s.recv(min(length - len(b), 4096))
        if not c: return None
        b.extend(c)
    return json.loads(b.decode('utf-8'))

def worker_sim(uid, lat_records, errors, iterations=6):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((TARGET_IP, TARGET_PORT))
        send_data = pack({"action": "register", "username": f"user_bench_{uid}"})
        sock.sendall(send_data)
        unpack(sock)

        for _ in range(iterations):
            start = time.perf_counter()
            sock.sendall(pack({"action": "chat", "message": f"ping_{uid}"}))
            resp = unpack(sock)
            end = time.perf_counter()
            if resp:
                lat_records.append((end - start) * 1000.0)
            time.sleep(0.01)
        sock.close()
    except Exception:
        errors[0] += 1

def run_tests():
    print("=" * 60)
    print(" RUNNING APPLICATION EVALUATION BENCHMARK")
    print("=" * 60)
    
    concurrency_steps = [5, 10, 20, 30, 50]
    print(f"{'Clients':<10}{'Mean Latency (ms)':<20}{'Median (ms)':<15}{'Errors':<10}")
    
    for count in concurrency_steps:
        latencies = []
        errs = [0]
        threads = []
        for i in range(count):
            th = threading.Thread(target=worker_sim, args=(f"{count}_{i}", latencies, errs))
            threads.append(th)
            th.start()
        for th in threads:
            th.join()

        mean_val = statistics.mean(latencies) if latencies else 0.0
        med_val = statistics.median(latencies) if latencies else 0.0
        print(f"{count:<10}{mean_val:<20.2f}{med_val:<15.2f}{errs[0]:<10}")

    print("\n[INSPECTING OVS OPENFLOW TABLES ON SWITCH s1]")
    try:
        flows = subprocess.check_output("ovs-ofctl dump-flows s1 -O OpenFlow13", shell=True).decode()
        for l in flows.strip().split("\n"):
            if "priority=" in l:
                print("  " + l.strip())
    except Exception as e:
        print(f"Could not read OVS flow tables: {e}")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        TARGET_IP = sys.argv[1]
    run_tests()