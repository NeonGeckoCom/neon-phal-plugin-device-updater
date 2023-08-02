# NEON AI (TM) SOFTWARE, Software Development Kit & Application Framework
# All trademark and other rights reserved by their respective owners
# Copyright 2008-2022 Neongecko.com Inc.
# Contributors: Daniel McKnight, Guy Daniels, Elon Gasper, Richard Leeds,
# Regina Bloomstine, Casimiro Ferreira, Andrii Pernatii, Kirill Hrymailo
# BSD-3 License
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from this
#    software without specific prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS  BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS;  OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE,  EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import unittest
import requests

from os import remove
from os.path import isfile, basename, join, dirname
from neon_phal_plugin_device_updater import DeviceUpdater
from ovos_utils.messagebus import FakeBus


class PluginTests(unittest.TestCase):
    bus = FakeBus()
    plugin = DeviceUpdater(bus)

    def test_build_info(self):
        self.assertIsInstance(self.plugin.build_info, dict)

    def test_check_initramfs_update_available(self):
        self.plugin.initramfs_real_path = join(dirname(__file__), "initramfs")
        with open(self.plugin.initramfs_real_path, 'w+') as f:
            f.write("test")
        self.assertTrue(self.plugin._check_initramfs_update_available())

        # Explicitly get valid initramfs
        with open(self.plugin.initramfs_real_path, 'wb') as f:
            f.write(requests.get(self.plugin.initramfs_url).content)
        self.assertFalse(self.plugin._check_initramfs_update_available())

        remove(self.plugin.initramfs_real_path)

    def test_get_initramfs_latest(self):
        # TODO
        pass

    def test_check_squashfs_update_available(self):
        # TODO
        pass

    def test_get_squashfs_latest(self):
        # TODO: Set up a fake directory for testing smaller file downloads
        # Empty build info
        self.plugin._build_info = dict()
        self.plugin.initramfs_update_path = "/tmp/update.sqfs"
        self.assertFalse(isfile(self.plugin.initramfs_update_path))

        # Download valid update
        file = self.plugin._get_squashfs_latest()
        self.assertTrue(isfile(file))

        # Already downloaded
        self.assertEqual(self.plugin._get_squashfs_latest(), file)

        # Already updated
        image_name, image_time = basename(file).rsplit('.', 1)[0].split('_', 1)
        self.plugin._build_info = {'base_os': {'name': image_name,
                                               'time': image_time}}
        self.assertIsNone(self.plugin._get_squashfs_latest())

    def test_check_update_initramfs(self):
        # TODO
        pass

    def test_check_update_squashfs(self):
        # TODO
        pass

    def test_update_squashfs(self):
        # TODO
        pass

    def test_update_initramfs(self):
        # TODO
        pass

if __name__ == '__main__':
    unittest.main()
