import microcontroller, storage, supervisor, traceback
import cc25xx_ui
import time

FS = storage.getmount("/")

if not cc25xx_ui.need_read():
    print("read lock file present, not reading")
elif FS.readonly:
    print("Resetting to remount FS for writing")
    microcontroller.reset()
else:
    print("Reading flash contents")
    try:
        cc25xx_ui.read_flash()
    except Exception as e:
        traceback.print_exception(e)
        time.sleep(5)
        # retry, let me see what's happening
        supervisor.reload()

    # Show green light
    time.sleep(5)
    # Return to RW for host
    microcontroller.reset()

if not cc25xx_ui.need_write():
    print("no new image to write, not writing")
elif FS.readonly:
    print("Resetting to remount FS for writing")
    microcontroller.reset()
else:
    print("Writing to flash")
    try:
        cc25xx_ui.write_flash()
    except Exception as e:
        traceback.print_exception(e)
        time.sleep(5)
        # retry, let me see what's happening
        supervisor.reload()

    # Show green light
    time.sleep(5)
    # Return to RW for host
    microcontroller.reset()

# restart to check locks again
time.sleep(5)
supervisor.reload()
