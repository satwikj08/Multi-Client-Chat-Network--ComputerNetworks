#!/usr/bin/env python3
"""
chat_topo.py - Mininet Diamond Topology connecting to POX SDN Controller
"""

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

class DiamondChatTopo(Topo):
    def build(self):
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')
        s4 = self.addSwitch('s4')

        server = self.addHost('h_server', ip='10.0.0.100/24', mac='00:00:00:00:00:64')
        self.addLink(server, s4, cls=TCLink, bw=25, delay='1ms')

        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
        h3 = self.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03')
        h4 = self.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04')

        for h in [h1, h2, h3, h4]:
            self.addLink(h, s1, cls=TCLink, bw=10, delay='2ms')

        # Fast path
        self.addLink(s1, s2, cls=TCLink, bw=10, delay='2ms')
        self.addLink(s2, s4, cls=TCLink, bw=10, delay='2ms')

        # Bottleneck path
        self.addLink(s1, s3, cls=TCLink, bw=2, delay='15ms')
        self.addLink(s3, s4, cls=TCLink, bw=2, delay='15ms')


def start_network():
    topo = DiamondChatTopo()
    # POX listens on standard port 6633
    controller = RemoteController('c0', ip='127.0.0.1', port=6633)
    net = Mininet(topo=topo, switch=OVSSwitch, controller=controller, link=TCLink)
    
    info('*** Starting Network\n')
    net.start()
    info('*** Checking Base Connectivity\n')
    net.pingAll()
    CLI(net)
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    start_network()