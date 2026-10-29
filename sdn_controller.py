#!/usr/bin/env python3
"""
sdn_controller.py - Dynamic SDN Policy Controller for Project 8
Runs inside POX: python3 ~/pox/pox.py forwarding.l2_learning sdn_controller
"""

from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.addresses import IPAddr, EthAddr
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading

log = core.getLogger()

class PolicyManager:
    """Manages active OpenFlow flow rules pushed by the Chat Server."""
    
    @staticmethod
    def block_ip(client_ip, duration=30):
        """Dynamic Firewall: Drop all traffic from offending IP at Switch level."""
        for connection in core.openflow.connections.values():
            msg = of.ofp_flow_mod()
            msg.priority = 65000  # Highest priority
            msg.match.dl_type = 0x0800  # IPv4
            msg.match.nw_src = IPAddr(client_ip)
            msg.hard_timeout = int(duration)
            msg.actions = []  # Empty actions = DROP
            connection.send(msg)
            log.info(f"[SDN-FIREWALL] Blocked IP {client_ip} on Switch dpid={connection.dpid} for {duration}s")

    @staticmethod
    def prioritize_ip(client_ip, room_name, priority_val=20000):
        """Dynamic QoS: Installs high-priority forwarding rule for VIP/Emergency chat."""
        for connection in core.openflow.connections.values():
            msg = of.ofp_flow_mod()
            msg.priority = int(priority_val)
            msg.match.dl_type = 0x0800
            msg.match.nw_proto = 6  # TCP
            msg.match.nw_src = IPAddr(client_ip)
            msg.idle_timeout = 120
            # Forward normally with higher table match priority
            msg.actions.append(of.ofp_action_output(port=of.OFPP_NORMAL))
            connection.send(msg)
            log.info(f"[SDN-QOS] Installed priority {priority_val} flow for {client_ip} ({room_name}) on Switch {connection.dpid}")


class RESTRequestHandler(BaseHTTPRequestHandler):
    """Simple REST API server listening on 8080."""
    
    def do_POST(self):
        content_len = int(self.headers.get('Content-Length', 0))
        post_body = self.rfile.read(content_len)
        try:
            data = json.loads(post_body.decode('utf-8'))
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        if self.path == '/chat/policy/prioritize':
            ip = data.get('client_ip')
            room = data.get('room', '#general')
            priority = data.get('priority', 20000)
            PolicyManager.prioritize_ip(ip, room, priority)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "success", "policy": "prioritize"}')

        elif self.path == '/chat/policy/block':
            ip = data.get('client_ip')
            duration = data.get('duration', 30)
            PolicyManager.block_ip(ip, duration)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "success", "policy": "block"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return  # Suppress default HTTP access logs


def run_rest_server():
    server = HTTPServer(('127.0.0.1', 8080), RESTRequestHandler)
    log.info("[SDN] REST Policy Bridge listening on http://127.0.0.1:8080")
    server.serve_forever()


def launch():
    """POX entry point."""
    log.info("Launching Project 8 SDN Policy Module...")
    t = threading.Thread(target=run_rest_server, daemon=True)
    t.start()
