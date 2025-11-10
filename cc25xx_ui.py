import storage
import re, time, microcontroller
from hex_reader import HexReader

FS = storage.getmount("/")

workdir    = "/cc25xx"
read_lock  = workdir + "/control.skip_flash_read"
read_image_basename = "data.read.bin"
read_image = workdir + "/" + read_image_basename

# Status indicator (auto-detects NeoPixel or single LED)
class _Indicator:
    def __init__(self):
        self.pin = None
        self.is_neopixel = False
        self._init()
    
    def _init(self):
        try:
            # Try NeoPixel first
            import neopixel_write, digitalio, board
            self.pin = digitalio.DigitalInOut(board.NEOPIXEL)
            self.pin.direction = digitalio.Direction.OUTPUT
            self.neopixel_write = neopixel_write.neopixel_write
            self.is_neopixel = True
        except:
            try:
                # Fallback to PWM LED for brightness control
                import pwmio, board
                self.pin = pwmio.PWMOut(board.LED, frequency=1000, duty_cycle=0)
            except:
                pass  # No indicator available
    
    def set(self, r, g, b):
        """Set status (color for NeoPixel, brightness for LED)"""
        if not self.pin:
            return
        if self.is_neopixel:
            self.neopixel_write(self.pin, bytearray([r, g, b]))
        else:
            # Use average of RGB as brightness (0-255 -> 0-65535)
            brightness = ((r + g + b) // 3) * 257
            self.pin.duty_cycle = brightness

    def blink(self, r, g, b, times=3, delay=0.2):
        """Blink status (color for NeoPixel, brightness for LED)"""
        if not self.pin:
            return
        for _ in range(times):
            self.set(r, g, b)
            time.sleep(delay)
            self.set(0, 0, 0)
            time.sleep(delay)

status_led = _Indicator()

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

def image_to_write_from():
    regex = re.compile(".*\.(bin|hex)$")
    for (f, _,_,_) in FS.ilistdir(workdir):
        if f == read_image_basename:
            continue
        if regex.match(f.lower()):
            return workdir + "/" + f
    return False

def need_write():
    if image_to_write_from():
        return True
    else:
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

    status_led.blink(10, 20, 10, 2)  # Cyan: initializing

    (chip_id, chip_name, chip_rev) = cc25xx_proto.debug_init()
    if not chip_name:
        status_led.blink(20, 0, 0, 3, 0.5)  # Red: error
        return False

    status_led.set(0, 0, 0)  # Off: starting

    nblocks = 256*1024 // blocksize
    for i in range(nblocks):
        cc25xx_proto.read_flash_memory_block(i*blocksize, buf)
        f.write(buf)
        # Blinking yellow while reading
        status_led.set(10 + i%2*6, 10 + (i+1)%2*6, 0)
        if i % 2 == 1:
            print("\rRead flash: [", "="*(i//2), " "*((nblocks-i)//2), "]", sep='', end='')

    status_led.set(0, 20, 0, 5)  # Green: success
    print("")
    return True



def write_flash(blocksize = 512):
    image = image_to_write_from()
    if not image:
        return False
    if re.match(".*\.bin$", image.lower()):
        with FS.open(image, "r") as d:
            result = write_flash_from_filedesc(d, blocksize=blocksize)
    elif re.match(".*\.hex$", image.lower()):
        reader = HexReader(image)
        result = write_flash_from_filedesc(reader, blocksize=blocksize)

    if result:
        FS.remove(image)
    return result

def write_flash_from_filedesc(f, blocksize = 512):
    import cc25xx_proto
    # Flash size of CC2531 is 256K
    # writing 2K stuck
    # So, some small configurable default
    #blocksize = 64
    buf = bytearray(blocksize)

    status_led.blink(10, 20, 10, 2)  # Cyan: initializing
    (chip_id, chip_name, chip_rev) = cc25xx_proto.debug_init()
    if not chip_name:
        status_led.blink(20, 0, 0, 3, 0.5)  # Red: error
        return False
    cc25xx_proto.prepare_for_writing()

    status_led.set(0, 0, 0)  # Off: starting

    nblocks = 256*1024 // blocksize
    rangediv = nblocks // 64
    for i in range(nblocks):
        readsz = f.readinto(buf)
        if not readsz:
            print("\nInput exausted")
            break
        if readsz < blocksize:
            # Pad missing part
            for i in range(readsz, blocksize):
                buf[i] = 0xff
        cc25xx_proto.write_flash_memory_block(i*blocksize, buf)
        # Blinking yellow/pink while writing
        status_led.set(10 + i%2*6, 5 + (i+1)%2*6, 5 + (i+1)%2*6)
        if (i+1) % rangediv == 0:
            print("\rWrite flash: [", "="*(i//rangediv), " "*((nblocks-i)//rangediv), "]", sep='', end='')

    status_led.blink(0, 20, 0, 5)  # Green: success
    print("")
    return True
