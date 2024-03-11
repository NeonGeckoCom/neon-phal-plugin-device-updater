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
import logging
import unittest
from tempfile import mkstemp
from time import time

import requests

from os import remove
from os.path import isfile, basename, join, dirname
from neon_phal_plugin_device_updater import DeviceUpdater
from ovos_utils.messagebus import FakeBus
from ovos_utils.log import LOG

LOG.level = logging.DEBUG


class PluginTests(unittest.TestCase):
    bus = FakeBus()
    plugin = DeviceUpdater(bus)

    def test_00_init(self):
        self.assertIsInstance(self.plugin.initramfs_url, str)
        self.assertIsInstance(self.plugin.initramfs_real_path, str)
        self.assertIsInstance(self.plugin.initramfs_update_path, str)
        self.assertIsInstance(self.plugin.squashfs_url, str)
        self.assertIsInstance(self.plugin.squashfs_path, str)

        self.plugin._default_branch = "dev"
        self.assertIsNone(self.plugin.initramfs_hash)
        self.assertIsInstance(self.plugin.build_info, dict)

    def test_check_initramfs_update_available(self):
        self.plugin.initramfs_real_path = join(dirname(__file__), "initramfs")
        with open(self.plugin.initramfs_real_path, 'w+') as f:
            f.write("test")
        self.plugin._initramfs_hash = None
        self.assertTrue(self.plugin._legacy_check_initramfs_update_available())

        # Explicitly get valid initramfs
        with open(self.plugin.initramfs_real_path, 'wb') as f:
            f.write(requests.get(
                self.plugin.initramfs_url.format(
                    self.plugin._default_branch)).content)
        self.plugin._initramfs_hash = None
        self.assertFalse(self.plugin._legacy_check_initramfs_update_available())

        remove(self.plugin.initramfs_real_path)

    def test_get_initramfs_latest(self):
        real_url = self.plugin.initramfs_url
        self.plugin._initramfs_hash = None

        # Check invalid URL
        self.plugin.initramfs_url = None
        with self.assertRaises(RuntimeError):
            self.plugin._get_initramfs_latest()
        self.plugin.initramfs_url = real_url

        # Update already downloaded and applied
        self.plugin._initramfs_hash = None
        self.plugin.initramfs_update_path = join(dirname(__file__), "update")
        self.plugin.initramfs_real_path = join(dirname(__file__), "initramfs")
        with open(self.plugin.initramfs_real_path, 'w+') as f:
            f.write("test")
        with open(self.plugin.initramfs_update_path, 'w+') as f:
            f.write("test")
        self.assertFalse(self.plugin._get_initramfs_latest())

        # Update already downloaded not applied
        self.plugin._initramfs_hash = None
        with open(self.plugin.initramfs_update_path, 'w') as f:
            f.write("test 2")
        self.assertTrue(self.plugin._get_initramfs_latest())

        # TODO: Test download hash
        remove(self.plugin.initramfs_update_path)
        remove(self.plugin.initramfs_real_path)

    def test_check_version_is_newer(self):
        new_version = "2023-08-04_16_30"
        old_version = "2023-08-04_10_30"

        self.assertFalse(self.plugin.check_version_is_newer(new_version,
                                                            old_version))
        self.assertTrue(self.plugin.check_version_is_newer(old_version,
                                                           new_version))
        self.assertFalse(self.plugin.check_version_is_newer(new_version,
                                                            new_version))

        # Test Timestamp
        now_time = time()
        self.assertFalse(self.plugin.check_version_is_newer(now_time,
                                                            old_version))
        self.assertTrue(self.plugin.check_version_is_newer(old_version,
                                                           now_time))

        # Test default behavior
        self.assertTrue(self.plugin.check_version_is_newer("2022", "2023"))

    def test_check_squashfs_update_available(self):
        self.plugin._build_info = dict()
        version, url = self.plugin._legacy_check_squashfs_update_available()
        self.assertIsInstance(version, str)
        self.assertTrue(url.startswith('http'))
        new_image_time = version.split('_', 1)[1].rsplit('.', 1)[0]

        # Current equals remote
        self.plugin._build_info = {"base_os": {"time": new_image_time}}
        self.assertIsNone(self.plugin._legacy_check_squashfs_update_available())

        # Current newer than remote
        new_image_time = f"3000-{new_image_time.split('-', 1)[1]}"
        self.plugin._build_info["base_os"]["time"] = new_image_time
        self.assertIsNone(self.plugin._legacy_check_squashfs_update_available())

        # Current older than remote
        old_image_time = f"2020-{new_image_time.split('_', 1)[1]}"
        self.plugin._build_info["base_os"]["time"] = old_image_time
        version2, url2 = self.plugin._legacy_check_squashfs_update_available()
        self.assertEqual(version, version2)
        self.assertEqual(url, url2)

    def test_get_squashfs_latest(self):
        # TODO: Set up a fake directory for testing smaller file downloads
        # Empty build info
        self.plugin._build_info = dict()
        self.plugin.initramfs_update_path = "/tmp/update.sqfs"
        self.assertFalse(isfile(self.plugin.initramfs_update_path))

        # Download valid update
        file = self.plugin._legacy_get_squashfs_latest()
        self.assertTrue(isfile(file))

        # Already downloaded
        self.assertEqual(self.plugin._legacy_get_squashfs_latest(), file)

        # Already updated
        image_name, image_time = basename(file).rsplit('.', 1)[0].split('_', 1)
        self.plugin._build_info = {'base_os': {'name': image_name,
                                               'time': image_time}}
        self.assertIsNone(self.plugin._legacy_get_squashfs_latest())

    def test_get_gh_latest_release(self):
        self.plugin._build_info = {"base_os": {"name": ""}}

        # Validate unknown image
        with self.assertRaises(RuntimeError):
            self.plugin._get_gh_latest_release_tag()

        # Validate pre-release
        self.plugin._build_info['base_os']['name'] = "debian-neon-image-rpi4"
        latest_dev_release = self.plugin._get_gh_latest_release_tag("dev")
        self.assertIsInstance(latest_dev_release, str)
        self.assertTrue("b" in latest_dev_release)

    def test_get_gh_release_meta_from_tag(self):
        self.plugin._build_info = {"base_os": {"name": ""}}

        # Validate unknown image
        with self.assertRaises(RuntimeError):
            self.plugin._get_gh_release_meta_from_tag("master")

        self.plugin._build_info['base_os']['name'] = "debian-neon-image-rpi4"

        # Validate unknown tag
        with self.assertRaises(ValueError):
            self.plugin._get_gh_release_meta_from_tag("00.01.01")

        # Validate valid release
        tag = "24.02.28.beta1"
        rpi_meta = self.plugin._get_gh_release_meta_from_tag(tag)
        self.assertEqual(rpi_meta['version'], '24.02.28b1')
        self.assertTrue('/rpi4/' in rpi_meta['download_url'])

        self.plugin._build_info['base_os']['name'] = "debian-neon-image-opi5"
        opi_meta = self.plugin._get_gh_release_meta_from_tag(tag)
        self.assertEqual(opi_meta['version'], '24.02.28b1')
        self.assertTrue('/opi5/' in opi_meta['download_url'])

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

    def test_stream_download_file(self):
        valid_os_url = "https://2222.us/app/files/neon_images/test_images/pi_image_3.img.xz"
        valid_update_file = "https://2222.us/app/files/neon_images/test_images/update_file.squashfs"
        invalid_update_file = "https://2222.us/app/files/neon_images/test_images/metadata.json"
        valid_path = "https://2222.us/app/files/neon_images/test_images/"
        invalid_path = "https://2222.us/app/files/neon_images/invalid_directory/"

        _, output_path = mkstemp()
        remove(output_path)

        self.plugin._stream_download_file(invalid_update_file, output_path)
        self.assertFalse(isfile(output_path))
        self.plugin._stream_download_file(valid_path, output_path)
        self.assertFalse(isfile(output_path))
        self.plugin._stream_download_file(invalid_path, output_path)
        self.assertFalse(isfile(output_path))

        self.plugin._stream_download_file(valid_os_url, output_path)
        self.assertTrue(isfile(output_path))
        remove(output_path)
        self.plugin._stream_download_file(valid_update_file, output_path)
        self.assertTrue(isfile(output_path))
        remove(output_path)


if __name__ == '__main__':
    unittest.main()
