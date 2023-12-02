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

    # Return to RW for host
    microcontroller.reset()

# restart to check locks again
time.sleep(5)
supervisor.reload()
