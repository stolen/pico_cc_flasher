import storage
import neopixel_write, digitalio, board

FS = storage.getmount("/")

workdir    = "/cc25xx"
read_lock  = workdir + "/control.skip_flash_read"
read_image = workdir + "/data.read.bin"

# Helper for cases where something is screwed up
def safe_mode():
    microcontroller.on_next_reset(microcontroller.RunMode.SAFE_MODE)
    microcontroller.reset()

def check_storage_on_boot():
    try:
        FS.ilistdir(workdir)
    except OSError as e:
        if e.errno == 2:
            storage.remount("/", readonly=False)
            FS.label = 'CC25xx_fl'
            FS.mkdir(workdir)

def need_read():
    try:
        FS.stat(read_lock)
        return False
    except OSError as e:
        if e.errno == 2:
            # No lock file, so yes, we need to read flash contents
            return True
        else:
            # Unknown error
            return False


def read_flash():
    with FS.open(read_image, "w") as d:
        result = read_flash_to_filedesc(d)

    if result:
        with FS.open(read_lock, "w") as f:
            pass
    else:
        time.sleep(5)

def read_flash_to_filedesc(f):
    import cc25xx_proto
    # Flash size of CC2531 is 256K
    # Reading 32K takes about 20 seconds
    # So, for visible activity, use 2K block
    blocksize = 2*1024
    buf = bytearray(blocksize)

    pin = digitalio.DigitalInOut(board.NEOPIXEL)
    pin.direction = digitalio.Direction.OUTPUT

    neopixel_write.neopixel_write(pin, bytearray([10,20,10]))
    (chip_id, chip_name, chip_rev) = cc25xx_proto.debug_init()
    if not chip_name:
        neopixel_write.neopixel_write(pin, bytearray([20,0,0]))
        return False

    neopixel_write.neopixel_write(pin, bytearray([0,0,0]))

    nblocks = 256*1024 // blocksize
    for i in range(nblocks):
        cc25xx_proto.read_flash_memory_block(i*blocksize, buf)
        f.write(buf)
        neopixel_write.neopixel_write(pin, bytearray([10+i%2*6, 10+(i+1)%2*6, 0]))
        if i % 2 == 1:
            print("\rRead flash: [", "="*(i//2), " "*((nblocks-i)//2), "]", sep='', end='')

    neopixel_write.neopixel_write(pin, bytearray([0,20,0]))
    print("")
    return True
