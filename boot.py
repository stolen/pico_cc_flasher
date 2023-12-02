import storage
import cc25xx_ui

FS = storage.getmount("/")

cc25xx_ui.check_storage_on_boot()

#if False:
if cc25xx_ui.need_read() or cc25xx_ui.need_write():
    storage.disable_usb_drive()
    storage.remount("/", readonly=False)
