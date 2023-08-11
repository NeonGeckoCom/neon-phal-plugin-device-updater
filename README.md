# Device Updater Plugin
Exposes a messagebus API to check for and initiate OS-level updates. This plugin
expects an `update-initramfs` system service to be installed to apply InitramFS
updates and for the SquashFS update path to be applied upon restarting.

## Configuration
The remote URLs and local paths for InitramFS and SquashFS files used by this plugin
may be set in configuration. The messagebus API supports `branch` in data which is
used to fill string templates in configured URLs; this is generally used to select a
git branch.

```yaml
PHAL:
  admin:
    neon-phal-plugin-device-updater:
      enabled: True
      initramfs_url: "https://github.com/NeonGeckoCom/neon_debos/raw/{}/overlays/02-rpi4/boot/firmware/initramfs"
      initramfs_path: /opt/neon/firmware/initramfs
      initramfs_update_path: /opt/neon/initramfs
      squashfs_url: "https://2222.us/app/files/neon_images/pi/mycroft_mark_2/updates/{}/"
      squashfs_path: /opt/neon/update.squashfs
      default_track: dev
```

## Messagebus API
The following Messagebus listeners are exposed by this plugin. The `track` data
parameter is optional and will default to the configured `default_track` if not
specified.

### Check for InitramFS Updates
Check for an available InitramFS update and emit a response with data: 
`update_available` and `track`.
```python
Message("neon.check_update_initramfs", {'track': 'dev'})
```

### Update InitramFS
Install an available InitramFS update and emit a response with data: 
`updated` and optionally `error`.
```python
Message("neon.update_initramfs", {'track': 'dev'})
```

### Check for SquashFS Updates
Check for an available SquashFS update and emit a response with data: 
`update_available` and `track`.
```python
Message("neon.check_update_squashfs", {'track': 'dev'})
```

### Update SquashFS
Check for an available InitramFS update and emit a response with data: 
`new_version` or `error`.
```python
Message("neon.update_squashfs", {'track': 'dev'})
```
