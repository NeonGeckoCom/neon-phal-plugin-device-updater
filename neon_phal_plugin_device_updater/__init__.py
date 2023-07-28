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
import requests

from os.path import isfile
from subprocess import Popen
from ovos_bus_client.message import Message
from ovos_utils.log import LOG
from ovos_plugin_manager.phal import PHALPlugin


class DeviceUpdater(PHALPlugin):
    def __init__(self, bus=None, name="neon-phal-plugin-device-updater",
                 config=None):
        PHALPlugin.__init__(self, bus, name, config)
        self.initramfs_url = self.config.get(
            "initramfs_url",
            "https://github.com/NeonGeckoCom/neon_debos/raw/dev/overlays/"
            "02-rpi4/boot/firmware/initramfs")
        self.initramfs_real_path = self.config.get("initramfs_path",
                                                   "/boot/firmware/initramfs")
        self.initramfs_update_path = self.config.get("initramfs_upadate_path",
                                                     "/opt/neon/initramfs")
        self.squashfs_url = self.config.get("squashfs_url")
        self.squashfs_path = self.config.get("squashfs_path",
                                             "/opt/neon/update.squashfs")

        # Register messagebus listeners
        self.bus.on("neon.update_initramfs", self.update_initramfs)

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
        with open(self.initramfs_update_path, 'wb+') as f:
            f.write(initramfs_request.content)
            f.seek(0)
            new_hash = hashlib.md5(f.read())
        with open("/boot/firmware/initramfs", 'rb') as f:
            old_hash = hashlib.md5(f.read())
        if new_hash == old_hash:
            LOG.debug("initramfs not changed")
            return False
        return True

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
