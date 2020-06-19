#!/usr/bin/env python

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
#
# Copyright: 2017 IBM
# Author: Prudhvi Miryala <mprudhvi@linux.vnet.ibm.com>
# Co-Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
Netperf is a benchmark that can be used to measure the performance of
many different types of networking. It provides tests for both
unidirectional throughput, and end-to-end latency.
"""


import os
import netifaces
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro
from avocado.utils import build
from avocado.utils import archive
from avocado.utils import process
from avocado.utils.genio import read_file
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils.ssh import Session


class Netperf(Test):
    """
    Netperf Test
    """

    def setUp(self):
        """
        To check and install dependencies for the test
        """
        self.peer_user = self.params.get("peer_user_name", default="root")
        self.peer_public_ip = self.params.get("peer_public_ip", default="")
        self.peer_ip = self.params.get("peer_ip", default="")
        self.peer_password = self.params.get("peer_password", '*',
                                             default="None")
        interfaces = netifaces.interfaces()
        self.iface = self.params.get("interface", default="")
        if self.iface not in interfaces:
            self.cancel("%s interface is not available" % self.iface)
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        local = LocalHost()
        self.networkinterface = NetworkInterface(self.iface, local)
        try:
            self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
            self.networkinterface.save(self.ipaddr, self.netmask)
        except Exception:
            self.networkinterface.save(self.ipaddr, self.netmask)
        self.networkinterface.bring_up()
        self.session = Session(self.peer_ip, user=self.peer_user,
                               password=self.peer_password)
        smm = SoftwareManager()
        detected_distro = distro.detect()
        pkgs = ['gcc']
        if detected_distro.name == "Ubuntu":
            pkgs.append('openssh-client')
        elif detected_distro.name == "SuSE":
            pkgs.append('openssh')
        else:
            pkgs.append('openssh-clients')
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
            cmd = "%s install %s" % (smm.backend.base_command, pkg)
            output = self.session.cmd(cmd)
            if not output.exit_status == 0:
                self.cancel("unable to install the package %s on peer machine "
                            % pkg)
        if self.peer_ip == "":
            self.cancel("%s peer machine is not available" % self.peer_ip)
        self.timeout = self.params.get("TIMEOUT", default="600")
        self.mtu = self.params.get("mtu", default=1500)
        self.remotehost = RemoteHost(self.peer_ip, self.peer_user,
                                     password=self.peer_password)
        self.peer_interface = self.remotehost.get_interface_by_ipaddr(self.peer_ip).name
        self.peer_networkinterface = NetworkInterface(self.peer_interface,
                                                      self.remotehost)
        self.remotehost_public = RemoteHost(self.peer_public_ip, self.peer_user,
                                            password=self.peer_password)
        self.peer_public_networkinterface = NetworkInterface(self.peer_interface,
                                                             self.remotehost_public)
        if self.peer_networkinterface.set_mtu(self.mtu) is not None:
            self.cancel("Failed to set mtu in peer")
        if self.networkinterface.set_mtu(self.mtu) is not None:
            self.cancel("Failed to set mtu in host")
        self.netperf_run = str(self.params.get("NETSERVER_RUN", default=0))
        self.netperf = os.path.join(self.teststmpdir, 'netperf')
        netperf_download = self.params.get("netperf_download", default="https:"
                                           "//github.com/HewlettPackard/"
                                           "netperf/archive/netperf-2.7.0.zip")
        tarball = self.fetch_asset(netperf_download, expire='7d')
        archive.extract(tarball, self.netperf)
        self.version = "%s-%s" % ("netperf",
                                  os.path.basename(tarball.split('.zip')[0]))
        self.neperf = os.path.join(self.netperf, self.version)
        cmd = "scp -r %s %s@%s:/tmp/" % (self.neperf, self.peer_user,
                                         self.peer_ip)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.cancel("unable to copy the netperf into peer machine")
        cmd = "cd /tmp/%s;./configure ppc64le;make" % self.version
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.fail("test failed because command failed in peer machine")
        os.chdir(self.neperf)
        process.system('./configure ppc64le', shell=True)
        build.make(self.neperf)
        self.perf = os.path.join(self.neperf, 'src', 'netperf')
        self.expected_tp = self.params.get("EXPECTED_THROUGHPUT", default="90")
        self.duration = self.params.get("duration", default="300")
        self.min = self.params.get("minimum_iterations", default="1")
        self.max = self.params.get("maximum_iterations", default="15")
        self.option = self.params.get("option", default='')

    def test(self):
        """
        netperf test
        """
        if self.netperf_run == '1':
            cmd = "chmod 777 /tmp/%s/src" % self.version
            output = self.session.cmd(cmd)
            if not output.exit_status == 0:
                self.fail("test failed because netserver not available")
            cmd = "/tmp/%s/src/netserver" % self.version
            output = self.session.cmd(cmd)
            if not output.exit_status == 0:
                self.fail("test failed because netserver not available")
        speed = int(read_file("/sys/class/net/%s/speed" % self.iface))
        cmd = "timeout %s %s -H %s" % (self.timeout, self.perf,
                                       self.peer_ip)
        if self.option != "":
            cmd = "%s -t %s" % (cmd, self.option)
        cmd = "%s -l %s -i %s,%s" % (cmd, self.duration, self.max,
                                     self.min)
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("FAIL: Run failed")
        for line in result.stdout.decode("utf-8").splitlines():
            if line and 'Throughput' in line.split()[-1]:
                tput = int(result.stdout.decode("utf-8").split()[-1].
                           split('.')[0])
                if tput < (int(self.expected_tp) * speed) / 100:
                    self.fail("FAIL: Throughput Actual - %s%%, Expected - %s%%"
                              ", Throughput Actual value - %s "
                              % ((tput*100)/speed, self.expected_tp,
                                 str(tput)+'Mb/sec'))

        if 'WARNING' in result.stdout.decode("utf-8"):
            self.log.warn('Test completed with warning')

    def tearDown(self):
        """
        removing the data in peer machine
        """
        cmd = "pkill netserver; rm -rf /tmp/%s" % self.version
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.fail("test failed because peer sys not connected")
        if self.networkinterface.set_mtu('1500') is not None:
            self.cancel("Failed to set mtu in host")
        try:
            self.peer_networkinterface.set_mtu('1500')
        except Exception:
            self.peer_public_networkinterface.set_mtu('1500')
        self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
        self.networkinterface.restore_from_backup()
        self.remotehost.remote_session.quit()
        self.remotehost_public.remote_session.quit()
