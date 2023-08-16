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

from datetime import datetime
from typing import Optional, Tuple, Union
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
        self.initramfs_url = self.config.get("initramfs_url",
                                             "https://github.com/NeonGeckoCom/"
                                             "neon_debos/raw/{}/overlays/"
                                             "02-rpi4/boot/firmware/initramfs")
        self.initramfs_real_path = self.config.get("initramfs_path",
                                                   "/opt/neon/firmware/initramfs")
        self.initramfs_update_path = self.config.get("initramfs_upadate_path",
                                                     "/opt/neon/initramfs")
        self.squashfs_url = self.config.get("squashfs_url",
                                            "https://2222.us/app/files/"
                                            "neon_images/pi/mycroft_mark_2/"
                                            "updates/{}/")
        self.squashfs_path = self.config.get("squashfs_path",
                                             "/opt/neon/update.squashfs")

        self._default_branch = self.config.get("default_track") or "master"
        self._build_info = None
        self._initramfs_hash = None

        # Register messagebus listeners
        self.bus.on("neon.check_update_initramfs", self.check_update_initramfs)
        self.bus.on("neon.update_initramfs", self.update_initramfs)
        self.bus.on("neon.check_update_squashfs", self.check_update_squashfs)
        self.bus.on("neon.update_squashfs", self.update_squashfs)

    @property
    def initramfs_hash(self) -> Optional[str]:
        """
        Get the MD5 hash of the currently installed InitramFS
        """
        if not self._initramfs_hash:
            try:
                Popen("mount_firmware", shell=True).wait(5)
                with open(self.initramfs_real_path, "rb") as f:
                    self._initramfs_hash = hashlib.md5(f.read()).hexdigest()
            except Exception as e:
                LOG.error(e)
                if isfile(self.initramfs_real_path):
                    with open(self.initramfs_real_path, "rb") as f:
                        self._initramfs_hash = hashlib.md5(f.read()).hexdigest()
        LOG.debug(f"hash={self._initramfs_hash}")
        return self._initramfs_hash

    @property
    def build_info(self) -> dict:
        """
        Get dict build information if available
        """
        if self._build_info is None:
            try:
                with open("/opt/neon/build_info.json") as f:
                    self._build_info = json.load(f)
            except Exception as e:
                LOG.error(f"Failed to get build info: {e}")
                self._build_info = dict()
        return self._build_info

    def _check_initramfs_update_available(self, branch: str = None) -> bool:
        """
        Check if there is a newer initramfs version available by comparing MD5
        @param branch: branch to format into initramfs_url
        @return: True if a newer initramfs is available to download
        """
        branch = branch or self._default_branch
        if not self.initramfs_url:
            raise RuntimeError("No initramfs_url configured")
        initramfs_url = self.initramfs_url.format(branch)
        md5_request = requests.get(f"{initramfs_url}.md5")
        if not md5_request.ok:
            LOG.warning(f"Unable to get md5 from {md5_request.url}; "
                        f"downloading latest initramfs")
            try:
                return self._get_initramfs_latest(branch)
            except ConnectionError as e:
                LOG.error(e)
                return False
        new_hash = md5_request.text.split('\n')[0]
        LOG.debug(f"new_hash={new_hash}")
        if new_hash == self.initramfs_hash:
            LOG.info("initramfs not changed")
            return False
        LOG.info("initramfs update available")
        return True

    def _get_initramfs_latest(self, branch: str = None) -> bool:
        """
        Get the latest initramfs image and check if it is different from the
        current installed initramfs
        @param branch: branch to format into initramfs_url
        @return: True if the downloaded initramfs file is different from current
        """
        branch = branch or self._default_branch
        if not self.initramfs_url:
            raise RuntimeError("No initramfs_url configured")
        if isfile(self.initramfs_update_path):
            LOG.info("update already downloaded")
            with open(self.initramfs_update_path, 'rb') as f:
                new_hash = hashlib.md5(f.read()).hexdigest()
        else:
            initramfs_url = self.initramfs_url.format(branch)
            LOG.debug(f"Getting initramfs from {initramfs_url}")
            initramfs_request = requests.get(initramfs_url)
            if not initramfs_request.ok:
                raise ConnectionError(f"Unable to get updated initramfs from: "
                                      f"{initramfs_url}")
            new_hash = hashlib.md5(initramfs_request.content).hexdigest()
            with open(self.initramfs_update_path, 'wb+') as f:
                f.write(initramfs_request.content)

        if new_hash == self.initramfs_hash:
            LOG.info("initramfs not changed. Removing downloaded file.")
            remove(self.initramfs_update_path)
            return False
        return True

    @staticmethod
    def check_version_is_newer(current: Union[str, int, float],
                               latest: Union[str, int, float]) -> bool:
        """
        Compare two image versions to check if an update is available
        @param current: currently installed version (timestamp or formatted)
        @param latest: latest available version from remote
        @return: True if latest is newer than current
        """
        try:
            date_format = "%Y-%m-%d_%H_%M"
            if isinstance(current, str):
                current_datetime = datetime.strptime(current, date_format)
            elif isinstance(current, (int, float)):
                current_datetime = datetime.fromtimestamp(current)
            else:
                raise TypeError(f"Expected formatted time or timestamp. "
                                f"Got: {current}")
            if isinstance(latest, str):
                latest_datetime = datetime.strptime(latest, date_format)
            elif isinstance(latest, (int, float)):
                latest_datetime = datetime.fromtimestamp(latest)
            else:
                raise TypeError(f"Expected formatted time or timestamp. "
                                f"Got: {latest}")
            if latest_datetime > current_datetime:
                return True
            return False
        except Exception as e:
            LOG.exception(e)
            # Parse failure, assume there's an update
            return True

    def _check_squashfs_update_available(self, track: str = None) \
            -> Optional[Tuple[str, str]]:
        """
        Check if a newer squashFS image is available and return the new version
        and download link.
        @param track: Update track (subdirectory) to check
        @return: new version and download link if available, else None
        """
        track = track or self._default_branch
        # Get all available update files from the configured URL
        ext = '.squashfs'
        prefix = self.build_info.get("base_os", {}).get("name", "")
        links = scrape_page_for_links(self.squashfs_url.format(track))
        valid_links = [(name, uri) for name, uri in links.items()
                       if name.endswith(ext) and name.startswith(prefix)]
        valid_links.sort(key=lambda k: k[0], reverse=True)
        newest_version = valid_links[0][0]
        download_url = valid_links[0][1]

        # Parse time of latest and current OS Image
        installed_image_time = self.build_info.get("base_os", {}).get("time")
        new_image_time = newest_version.split('_', 1)[1].rsplit('.', 1)[0]

        # Compare latest version with current
        if installed_image_time == new_image_time:
            LOG.info(f"Already Updated ({new_image_time}")
        elif self.check_version_is_newer(installed_image_time, new_image_time):
            LOG.info(f"New squashFS: {newest_version}")
            return newest_version, download_url
        else:
            LOG.info(f"Installed image ({installed_image_time}) is newer "
                     f"than latest ({new_image_time})")

    def _get_squashfs_latest(self, track: str = None) -> Optional[str]:
        """
        Get the latest squashfs image if different from the installed version
        @param track: update track (subdirectory) to check
        @return: path to downloaded update if present, else None
        """
        track = track or self._default_branch
        # Check for an available update
        update = self._check_squashfs_update_available(track)
        if not update:
            # Already updated
            return None
        newest_version, download_url = update

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

    def check_update_initramfs(self, message: Message):
        """
        Handle a request to check for initramfs updates
        @param message: `neon.check_update_initramfs` Message
        """
        branch = message.data.get("track") or self._default_branch
        update_available = self._check_initramfs_update_available(branch)
        self.bus.emit(message.response({"update_available": update_available,
                                        "track": branch}))

    def check_update_squashfs(self, message: Message):
        """
        Handle a request to check for squash updates
        @param message: `neon.check_update_squashfs` Message
        """
        track = message.data.get("track") or self._default_branch
        update_available = self._check_squashfs_update_available(track) is not None
        self.bus.emit(message.response({"update_available": update_available,
                                        "track": track}))

    def update_squashfs(self, message: Message):
        """
        Handle a request to update squashfs
        @param message: `neon.update_squashfs` Message
        """
        try:
            track = message.data.get("track") or self._default_branch
            LOG.info(f"Checking squashfs update: {track}")
            update = self._get_squashfs_latest(track)
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
            branch = message.data.get("track") or self._default_branch
            LOG.info("Performing initramfs update")
            if not isfile(self.initramfs_real_path) and \
                    not message.data.get("force_update"):
                LOG.debug("No initramfs to update")
                response = message.response({"updated": None,
                                             "error": "No initramfs to update"})
            elif not self._get_initramfs_latest(branch):
                LOG.info("No initramfs update")
                response = message.response({"updated": False})
            else:
                LOG.debug("Updating initramfs")
                proc = Popen("systemctl start update-initramfs", shell=True)
                success = proc.wait(30) == 0
                if success:
                    LOG.info("Updated initramfs")
                    self._initramfs_hash = None  # Update on next check
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
