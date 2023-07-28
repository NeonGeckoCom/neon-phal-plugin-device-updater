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

import hashlib
import json
import shutil

import requests

from typing import Optional
from os import remove
from os.path import isfile, join, dirname
from subprocess import Popen
from ovos_bus_client.message import Message
from ovos_utils.log import LOG
from ovos_plugin_manager.phal import PHALPlugin
from neon_utils.web_utils import scrape_page_for_links


class DeviceUpdater(PHALPlugin):
    def __init__(self, bus=None, name="neon-phal-plugin-device-updater",
                 config=None):
        PHALPlugin.__init__(self, bus, name, config)
        # TODO: Automate uploads or forwarding to account for repo changes
        self.initramfs_url = self.config.get("initramfs_url",
                                             "https://github.com/NeonGeckoCom/"
                                             "neon_debos/raw/dev/overlays/"
                                             "02-rpi4/boot/firmware/initramfs")
        self.initramfs_real_path = self.config.get("initramfs_path",
                                                   "/boot/firmware/initramfs")
        self.initramfs_update_path = self.config.get("initramfs_upadate_path",
                                                     "/opt/neon/initramfs")
        self.squashfs_url = self.config.get("squashfs_url",
                                            "https://2222.us/app/files/"
                                            "neon_images/pi/mycroft_mark_2/"
                                            "updates/")
        self.squashfs_path = self.config.get("squashfs_path",
                                             "/opt/neon/update.squashfs")

        self._build_info = None

        # Register messagebus listeners
        self.bus.on("neon.update_initramfs", self.update_initramfs)
        self.bus.on("neon.update_squashfs", self.update_squashfs)

    @property
    def build_info(self) -> dict:
        if self._build_info is None:
            try:
                with open("/opt/neon/build_info.json") as f:
                    self._build_info = json.load(f)
            except Exception as e:
                LOG.error(f"Failed to get build info: {e}")
                self._build_info = dict()
        return self._build_info

    def _get_initramfs_latest(self) -> bool:
        """
        Get the latest initramfs image and check if it is different from the
        current installed initramfs
        """
        if not self.initramfs_url:
            raise RuntimeError("No initramfs_url configured")
        initramfs_request = requests.get(self.initramfs_url)
        if not initramfs_request.ok:
            raise ConnectionError(f"Unable to get updated initramfs from: "
                                  f"{self.initramfs_url}")
        new_hash = hashlib.md5(initramfs_request.content).hexdigest()
        with open(self.initramfs_update_path, 'wb+') as f:
            f.write(initramfs_request.content)
        with open("/boot/firmware/initramfs", 'rb') as f:
            old_hash = hashlib.md5(f.read()).hexdigest()
        if new_hash == old_hash:
            LOG.debug("initramfs not changed")
            return False
        return True

    def _get_squashfs_latest(self) -> Optional[str]:
        """
        Get the latest squashfs image if different from the installed version
        @returns: path to downloaded update if present, else None
        """

        # Get all available update files from the configured URL
        ext = '.squashfs'
        prefix = self.build_info.get("base_os", {}).get("name", "")
        links = scrape_page_for_links(self.squashfs_url)
        valid_links = [(name, uri) for name, uri in links.items()
                       if name.endswith(ext) and name.startswith(prefix)]
        valid_links.sort(key=lambda k: k[0], reverse=True)
        newest_version = valid_links[0][0]
        download_url = valid_links[0][1]

        # Check if the latest version matches the installed version
        installed_image_time = self.build_info.get("base_os", {}).get("time")
        if installed_image_time and installed_image_time in newest_version:
            LOG.info("Already updated")
            return None

        # Check if the updated version has already been downloaded
        download_path = join(dirname(self.initramfs_update_path),
                             newest_version)
        if isfile(download_path):
            LOG.info("Update already downloaded")
            return download_path

        # Download the update
        LOG.info(f"Downloading update from {download_url}")
        temp_dl_path = f"{download_path}.download"
        try:
            with requests.get(download_url, stream=True) as stream:
                with open(temp_dl_path, 'wb') as f:
                    for chunk in stream.iter_content(4096):
                        if chunk:
                            f.write(chunk)
            shutil.move(temp_dl_path, download_path)
            return download_path
        except Exception as e:
            LOG.exception(e)
            if isfile(temp_dl_path):
                remove(temp_dl_path)

    def update_squashfs(self, message: Message):
        """
        Handle a request to update squashfs
        @param message: `neon.update_squashfs` Message
        """
        try:
            LOG.info("Checking squashfs update")
            update = self._get_squashfs_latest()
            if update:
                LOG.info("Update available and will be installed on restart")
                shutil.copyfile(update, self.squashfs_path)
                response = message.response({"new_version": update})
            else:
                LOG.info("Already updated")
                response = message.response({"new_version": None})
        except Exception as e:
            LOG.exception(e)
            response = message.response({"error": repr(e)})
        self.bus.emit(response)

    def update_initramfs(self, message: Message):
        """
        Handle a request to update initramfs
        @param message: `neon.update_initramfs` Message
        """
        try:
            LOG.info("Checking initramfs update")
            if not isfile(self.initramfs_real_path):
                LOG.debug("No initramfs to update")
                response = message.response({"updated": None})
            elif not self._get_initramfs_latest():
                LOG.debug("No initramfs update")
                response = message.response({"updated": False})
            else:
                LOG.debug("Updating initramfs")
                proc = Popen("systemctl start update-initramfs", shell=True)
                success = proc.wait(30) == 0
                if success:
                    LOG.info("Updated initramfs")
                    response = message.response({"updated": success})
                else:
                    LOG.error(f"Update service exited with error: {success}")
                    response = message.response({"updated": False,
                                                 "error": str(success)})
        except Exception as e:
            LOG.error(e)
            response = message.response({"updated": None,
                                         "error": repr(e)})
        self.bus.emit(response)
