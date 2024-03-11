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
from os.path import isfile, join, dirname, getsize
from subprocess import Popen

import yaml
from ovos_bus_client.message import Message
from ovos_utils.log import LOG, log_deprecation
from ovos_plugin_manager.phal import PHALPlugin
from neon_utils.web_utils import scrape_page_for_links


class DeviceUpdater(PHALPlugin):
    def __init__(self, bus=None, name="neon-phal-plugin-device-updater",
                 config=None):
        PHALPlugin.__init__(self, bus, name, config)
        self.initramfs_real_path = self.config.get(
            "initramfs_path", "/opt/neon/firmware/initramfs")
        self.initramfs_update_path = self.config.get("initramfs_upadate_path",
                                                     "/opt/neon/initramfs")
        self.release_repo = self.config.get("release_repo",
                                            "NeonGeckoCom/neon-os")
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
        self.bus.on("neon.device_updater.check_update",
                    self.check_update_available)
        self.bus.on("neon.device_updater.get_build_info",
                    self.get_build_info)

    @property
    def squashfs_url(self):
        log_deprecation("FTP update references are deprecated.", "1.0.0")
        return self.config.get("squashfs_url", "https://2222.us/app/files/"
                                               "neon_images/pi/mycroft_mark_2/"
                                               "updates/{}/")

    @property
    def initramfs_url(self):
        return self.config.get("initramfs_url",
                               "https://github.com/NeonGeckoCom/neon_debos/raw/"
                               "{}/overlays/02-rpi4/boot/firmware/initramfs")

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

    def _legacy_check_initramfs_update_available(self,
                                                 branch: str = None) -> bool:
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
        LOG.info(f"initramfs update available (new={new_hash}|"
                 f"old={self.initramfs_hash}")
        return True

    def _get_initramfs_latest(self, branch: str = None) -> bool:
        """
        Get the latest initramfs image and check if it is different from the
        current installed initramfs. This will save the updated file locally,
        but will not apply the update.
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

    def _legacy_check_squashfs_update_available(self, track: str = None) \
            -> Optional[Tuple[str, str]]:
        """
        Check if a newer squashFS image is available and return the new version
        and download link.
        @param track: Update track (subdirectory) to check
        @return: new version (filename) and download link if available, else None
        """
        track = track or self._default_branch
        # Get all available update files from the configured URL
        ext = '.squashfs'
        prefix = self.build_info.get("base_os", {}).get("name", "")
        remote = self.squashfs_url.format(track)
        links = scrape_page_for_links(remote)
        valid_links = [(name, uri) for name, uri in links.items()
                       if name.endswith(ext) and name.startswith(prefix)]
        valid_links.sort(key=lambda k: k[0], reverse=True)
        LOG.debug(f"Got versions from {remote}: {valid_links}")
        newest_version = valid_links[0][0]
        download_url = valid_links[0][1]

        # Parse time of latest and current OS Image
        installed_image_time = self.build_info.get("base_os", {}).get("time")
        new_image_time = newest_version.split('_', 1)[1].rsplit('.', 1)[0]

        # Compare latest version with current
        if installed_image_time == new_image_time:
            LOG.info(f"Already Updated ({new_image_time})")
        elif self.check_version_is_newer(installed_image_time, new_image_time):
            LOG.info(f"New squashFS: {newest_version}")
            return newest_version, download_url
        else:
            LOG.info(f"Installed image ({installed_image_time}) is newer "
                     f"than latest ({new_image_time})")

    def _legacy_get_squashfs_latest(self, track: str = None) -> Optional[str]:
        """
        Get the latest squashfs image if different from the installed version
        @param track: update track (subdirectory) to check
        @return: path to downloaded update if present, else None
        """
        track = track or self._default_branch
        # Check for an available update
        update = self._legacy_check_squashfs_update_available(track)
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

        return self._stream_download_file(download_url, download_path)

    @staticmethod
    def _stream_download_file(download_url: str,
                              download_path: str) -> Optional[str]:
        """
        Download a remote resource to a local path and return the path to the
        written file. This will provide some trivial validation that the output
        file is an OS update.
        @param download_url: URL of file to download
        @param download_path: path of output file
        @return: actual path to output file
        """
        # Download the update
        LOG.info(f"Downloading update from {download_url}")
        temp_dl_path = f"{download_path}.download"
        try:
            with requests.get(download_url, stream=True) as stream:
                with open(temp_dl_path, 'wb') as f:
                    for chunk in stream.iter_content(4096):
                        if chunk:
                            f.write(chunk)
            # Update should be > 100MiB
            file_mib = getsize(temp_dl_path) / 1048576
            if file_mib < 100:
                LOG.error(f"Downloaded file is too small ({file_mib}MiB)")
                remove(temp_dl_path)
                return
            shutil.move(temp_dl_path, download_path)
            LOG.info(f"Saved download to {download_path}")
            return download_path
        except Exception as e:
            LOG.exception(e)
            if isfile(temp_dl_path):
                remove(temp_dl_path)

    def _get_gh_latest_release_tag(self, track: str = None) -> str:
        """
        Get the GitHub release tag associated with the latest version of the
        installed OS (on the requested track). Note that the latest GitHub
        release may not be relevant to the installed OS
        @param track: "beta" or "stable" release track. An invalid request will
            default to "stable"
        @return: String tag in `self.release_repo` corresponding to the newest
            valid release
        """
        include_prerelease = (track or self._default_branch) in ("dev", "beta")

        default_time = "2000-01-01T00:00:00Z"
        url = f'https://api.github.com/repos/{self.release_repo}/releases'
        releases: list = requests.get(url).json()
        if not include_prerelease:
            releases = [r for r in releases if not r.get('prerelease', True)]
        installed_os = self.build_info.get("base_os", {}).get("name")
        if not installed_os:
            raise RuntimeError(f"Unable to determine installed OS from: "
                               f"{self.build_info}")
        releases = [r for r in releases if installed_os in r.get('body', '')]
        releases.sort(key=lambda r: datetime.strptime(r.get('created_at',
                                                            default_time),
                                                      "%Y-%m-%dT%H:%M:%SZ"),
                      reverse=True)
        return releases[0].get('tag_name')

    def _get_gh_release_meta_from_tag(self, tag: str) -> dict:
        """
        Get release metadata for the installed OS at the requested `tag`
        @param tag: Release tag to get metadata from
        @return: dict latest release data for the requested tag
        """
        installed_os = self.build_info.get("base_os", {}).get("name")
        if not installed_os:
            raise RuntimeError(f"Unable to determine installed OS from: "
                               f"{self.build_info}")
        meta_url = (f"https://raw.githubusercontent.com/{self.release_repo}/"
                    f"{tag}/{installed_os}.yaml")
        resp = requests.get(meta_url)
        if not resp.ok:
            raise ValueError(f"Unable to get metadata for tag={tag}")
        meta_text = resp.text
        release_meta = yaml.safe_load(meta_text)

        return release_meta[0]

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

    def check_update_initramfs(self, message: Message):
        """
        Handle a request to check for initramfs updates
        @param message: `neon.check_update_initramfs` Message
        """
        branch = message.data.get("track") or self._default_branch
        try:
            meta = self._get_gh_release_meta_from_tag(
                self._get_gh_latest_release_tag(self._default_branch))
            update_available = meta['initramfs']['md5'] != self.initramfs_hash
        except Exception as e:
            LOG.exception(e)
            update_available = self._legacy_check_initramfs_update_available(branch)
        self.bus.emit(message.response({"update_available": update_available,
                                        "track": branch}))

    def check_update_squashfs(self, message: Message):
        """
        Handle a request to check for squash updates
        @param message: `neon.check_update_squashfs` Message
        """
        track = message.data.get("track") or self._default_branch
        try:
            tag = self._get_gh_latest_release_tag(track)
            if self._build_info.get('version') and \
                    self._build_info['version'] == tag:
                LOG.debug(f"Already up to date")
                update_available = False
                update_meta = None
            else:
                update_meta = self._get_gh_release_meta_from_tag(tag)
                update_available = (
                        update_meta['base_os'] != self._build_info['base_os'])
        except Exception as e:
            LOG.info(f"Falling back to legacy update check: {e}")
            response = self._legacy_check_squashfs_update_available(track)

            if response:
                update_available = True
                new_version, download_url = response
                # Get metadata for new version
                meta_url = download_url.replace(".squashfs", ".json")
                try:
                    resp = requests.get(meta_url)
                    if resp.ok:
                        update_meta = resp.json()
                    else:
                        LOG.warning(f"Unable to get metadata: "
                                    f"{resp.status_code}")
                        update_meta = dict()
                except Exception as e:
                    LOG.exception(e)
                    update_meta = dict()
                update_meta["download_url"] = download_url
            else:
                update_available = False
                update_meta = None

        self.bus.emit(message.response({"update_available": update_available,
                                        "update_metadata": update_meta,
                                        "track": track}))

    def update_squashfs(self, message: Message):
        """
        Handle a request to update squashfs
        @param message: `neon.update_squashfs` Message
        """
        track = message.data.get("track") or self._default_branch
        LOG.info(f"Checking squashfs update: {track}")
        update_metadata = message.data.get("update_metadata")
        try:
            if not update_metadata:
                update_metadata = self._get_gh_release_meta_from_tag(
                    self._get_gh_latest_release_tag(track))
            platform = self.build_info['base_os']['platform']
            download_url = update_metadata['download_url'].replace(
                f"/{platform}/", f"/{platform}/updates/").replace(".img.xz",
                                                                  ".squashfs")
            download_path = join(dirname(self.initramfs_update_path),
                                 update_metadata['build_version'])
            if isfile(download_path):
                LOG.info("Update already downloaded")
                return download_path
            update_file = self._stream_download_file(download_url,
                                                     download_path)
        except Exception as e:
            LOG.exception(f"Failed to get download_url: {e}")
            update_file = self._legacy_get_squashfs_latest(track)

        try:
            if update_file:
                LOG.info("Update downloaded and will be installed on restart")
                shutil.copyfile(update_file, self.squashfs_path)
                response = message.response({"new_version": update_file})
            else:
                LOG.info("Already updated")
                response = message.response({"new_version": None})
        except Exception as e:
            LOG.exception(e)
            response = message.response({"error": repr(e)})
        self.bus.emit(response)

    def update_initramfs(self, message: Message):
        """
        Handle a request to update initramfs.
        @param message: `neon.update_initramfs` Message
        """
        branch = message.data.get("track") or self._default_branch
        LOG.info("Performing initramfs update")
        if not isfile(self.initramfs_real_path) and \
                not message.data.get("force_update"):
            LOG.debug("No initramfs to update")
            response = message.response({"updated": None,
                                         "error": "No initramfs to update"})
            self.bus.emit(response)
            return
        try:
            meta = self._get_gh_release_meta_from_tag(
                self._get_gh_latest_release_tag(branch))
            branch = meta['image']['version']
        except Exception as e:
            LOG.error(f"Failed to get image version for branch {branch}: {e}")
        try:
            if not self._get_initramfs_latest(branch):
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

    def check_update_available(self, message: Message):
        """
        Handle a request to check for OS updates
        @param message: `neon.device_updater.check_update` Message
        """
        track = "beta" if message.data.get("include_prerelease") else "stable"
        installed_version = self.build_info.get("build_version")
        latest_version = self._get_gh_latest_release_tag(track)
        self.bus.emit(message.response({"installed_version": installed_version,
                                        "latest_version": latest_version}))

    def get_build_info(self, message: Message):
        """
        Handle a request to check for current OS build info
        @param message: `neon.device_updater.get_build_info` Message
        """
        self.bus.emit(message.response(self.build_info))
