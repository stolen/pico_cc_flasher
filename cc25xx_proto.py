import rp2pio
import adafruit_pioasm
from array import array
import board
import time

# seems like RP2040 cannot sample fast enough
# Maybe with second input-only pin on DD reads will be more reliable
# 25 MHz clock   --  ~8 Mbps bitrate
pio_frequency = 25_000_000

pinDD  = board.GP27
# DC and RST must be consecutive because they are set by pio side-set
pinDC  = board.GP28
pinRST = board.GP29



sm = None
loaded_sm = None

ADDR_BUF0                 = 0x0000 # Buffer (512 bytes)
ADDR_DMA_DESC_0           = 0x0200 # DMA descriptors (8 bytes)
ADDR_DMA_DESC_1           = (ADDR_DMA_DESC_0 + 8)
CH_DBG_TO_BUF0            = 0x01   # Channel 0
CH_BUF0_TO_FLASH          = 0x02   # Channel 1

# DUP registers (XDATA space address)
DUP_DBGDATA               = 0x6260  #  Debug interface data buffer
DUP_FCTL                  = 0x6270  #  Flash controller
DUP_FADDRL                = 0x6271  #  Flash controller addr
DUP_FADDRH                = 0x6272  #  Flash controller addr
DUP_FWDATA                = 0x6273  #  Clash controller data buffer
DUP_CLKCONSTA             = 0x709E  #  Sys clock status
DUP_CLKCONCMD             = 0x70C6  #  Sys clock configuration
DUP_MEMCTR                = 0x70C7  #  Flash bank xdata mapping
DUP_DMA1CFGL              = 0x70D2  #  Low byte, DMA config ch. 1
DUP_DMA1CFGH              = 0x70D3  #  Hi byte , DMA config ch. 1
DUP_DMA0CFGL              = 0x70D4  #  Low byte, DMA config ch. 0
DUP_DMA0CFGH              = 0x70D5  #  Low byte, DMA config ch. 0
DUP_DMAARM                = 0x70D6  #  DMA arming register

def HIBYTE(addr):
    return (addr >> 8) & 0xff
def LOBYTE(addr):
    return addr & 0xff


# 1) Pull RESET_N low
# 2) Toggle two negative flanks on the DC line
# 3) Pull RESET_N high
debug_init_asm = """
.program init_dbg
.side_set 2 opt
    set pins, 0     side 0  [3]     ; RST low, DC low

    set pindirs, 1  side 1          ; DC flank 1
    nop             side 0  [2]

    nop             side 1          ; DC flank 2
    nop             side 0  [3]

    nop             side 2          ; RST high
"""
debug_init_compiled = adafruit_pioasm.assemble(debug_init_asm)


# Debug commands
#
# CMD_CHIP_ERASE              0x10
# CMD_WR_CONFIG               0x19
# CMD_RD_CONFIG               0x24
# CMD_READ_STATUS             0x30
# CMD_RESUME                  0x4C
# CMD_DEBUG_INSTR_1B          (0x54|1)
# CMD_DEBUG_INSTR_2B          (0x54|2)
# CMD_DEBUG_INSTR_3B          (0x54|3)
# CMD_BURST_WRITE             0x80
# CMD_GET_CHIP_ID             0x68
#
# least significant 2 bits are number of bytes following instruction
# Every command fits into 32-bit word
debug_command_asm = """
.program debug_command
.side_set 2 opt
next_command:
    pull                            ; wait for next command, ensure clock low

    out x, 16          side 2       ; number of bytes to write
    mov isr osr                     ; keep read commands safe

    jmp x-- write_data
    jmp write_done

write_data:
    set pindirs 1       side 2      ; DD output
    pull                            ; payload is in following words
write_byte:
    pull ifempty
    set y 7                         ;
write_bit:
    out pins, 1         side 3      ; set data bit, clock high
    jmp y-- write_bit   side 2      ; clock low
    jmp x-- write_byte

    set pindirs 0                   ; DD input
    mov osr isr                     ; restore read commands

write_done:
    out x, 8                        ; X = 0 -> don't wait
                                    ; X = 1 -> wait ready

;wait_ready:                         ; drop byte until X = 0
    jmp !x wait_done

.wrap_target
    mov isr null                    ; ISR = 0
    in pins, 1                      ; ISR = DD
    mov x isr                       ; X = ISR -> X = DD
    jmp !x wait_done

wait_more:
    set y 7                         ;
drop_bit:
    nop                 side 3
    jmp y-- drop_bit    side 2
.wrap


wait_done:
    out x, 8                        ; number of bytes to read
    jmp x-- read_byte
    jmp command_done

read_byte:
    set y 7             side 2      ; 8 bits
read_bit:
    nop                 side 3 [2]  ; DUP sets bit at rising clock edge, let it settle
    in pins, 1          side 2      ; read at falling clock edge
    jmp y-- read_bit

    jmp x-- read_byte

command_done:
    push
"""
# Tdir_change is 83 ns, ~0.1us -- may use any speed because 4 ticks are always more
debug_command_prog = adafruit_pioasm.Program(debug_command_asm)


def ensure_sm(sm_id, prog):
    global loaded_sm, sm
    global pinRST, pinDD, pinDC

    if loaded_sm == sm_id:
        return loaded_sm
    if sm:
        abort_sm()

    sm = start_new_sm(prog)
    loaded_sm = sm_id
    return loaded_sm


def start_new_sm(prog):
    new_sm = rp2pio.StateMachine(
        prog.assembled,
        frequency = pio_frequency,

        exclusive_pin_use = False,

        first_set_pin = pinDD,
        initial_set_pin_direction = 0,

        first_out_pin = pinDD,
        out_pin_count = 1,
        initial_out_pin_direction = 0,   # for pull-up
        initial_out_pin_state = 0,

        first_in_pin = pinDD,
        in_pin_count = 1,
        pull_in_pin_up = True,

        jmp_pin = pinDD,

        first_sideset_pin = pinDC,          # second is pinRST
        initial_sideset_pin_state = 2,      # DC low, RST high
        initial_sideset_pin_direction = 0x1f,

        auto_pull = False,
        auto_push = False,
        out_shift_right = False,
        in_shift_right = False,

        user_interruptible = True,

        **prog.pio_kwargs
    )
    return new_sm

def abort_sm():
    global sm, loaded_sm
    if sm:
        sm.stop()
        sm.deinit()
        sm = None
    loaded_sm = None



def debug_init():
    global sm
    # perform debug_init sequence
    for i in range(len(debug_init_compiled)):
        sm.run(debug_init_compiled[i:i+1])
    (chip_id, chip_name, chip_rev) = read_chip_id()
    if not chip_name:
        print("Skipping XOSC init")
        return (chip_id, chip_name, chip_rev)
    write_xdata_memory(DUP_CLKCONCMD, 0x80);
    sta = 0
    while sta != 0x80:
        sta = read_xdata_memory(DUP_CLKCONSTA)
        print("clock status %02X" % sta)
    return (chip_id, chip_name, chip_rev)


def read_chip_id():
    global sm
    sm.clear_rxfifo()

    buf = array("L", [0x0001_00_02, 0x68000000])
    # read ChipID
    sm.background_write(buf); sm.readinto(buf, end=1)
    chip_id = (buf[0] >> 8) & 0xff
    chip_rev = buf[0] & 0xff

    if chip_id == 0xA5:
        chip_name = "CC2530"
    elif chip_id == 0xB5:
        chip_name = "CC2531"
    elif chip_id == 0x95:
        chip_name = "CC2533"
    elif chip_id == 0x43:
        chip_name = "CC2543"
    elif chip_id == 0x44:
        chip_name = "CC2544"
    elif chip_id == 0x45:
        chip_name = "CC2545"
    else:
        chip_name = None

    return (chip_id, chip_name, chip_rev)


def debug_command(cmd):
    global sm

    control = ((cmd >> 8) & 0x0003_0000) + 0x0001_01_01
    buf = array("L", [control, cmd])

    sm.clear_rxfifo()
    sm.background_write(buf)
    sm.readinto(buf, end=1)

    return buf[0] & 0xff


ensure_sm(0, debug_command_prog)



def write_xdata_memory(address, value):
    # MOV DPTR, address
    debug_command(0x57_90_0000 | (address & 0xffff))
    # MOV A, value
    debug_command(0x56_74_0000 | ((value & 0xff) << 8))
    # MOV @DPTR, A
    debug_command(0x55_F0_0000)

def read_xdata_memory(address):
    # MOV DPTR, address
    debug_command(0x57_90_0000 | (address & 0xffff))
    # MOVX A, @DPTR
    return debug_command(0x55_E0_0000)

def write_xdata_memory_block(address, values):
    # MOV DPTR, address
    debug_command(0x57_90_0000 | (address & 0xffff))

    for i in range(len(values)):
        # MOV A, values[i]
        debug_command(0x56_74_0000 | ((values[i] & 0xff) << 8))
        # MOV @DPTR, A
        debug_command(0x55_F0_0000)
        # INC DPTR
        debug_command(0x55_A3_0000)


def burst_write_block(buffer):
    global sm

    # Send command (no wait, no ack)
    control = 0x0002_00_00
    cmd = (0x8000 | len(buffer)) << 16
    buf = array("L", [control, cmd])
    sm.background_write(buf)
    sm.readinto(buf, end=1)

    # Send data (with ack)
    control = (len(buffer) << 16) | 0x0101
    buf = array("L", [control])
    sm.background_write(buf)
    for i in range(0, len(buffer), 4):
        buf[0] = int.from_bytes(buffer[i:i+4], 'big')
        sm.background_write(buf)
    sm.readinto(buf, end=1)
    return buf[0] & 0xff



def read_flash_memory_block(address, buffer):
    # 1. Map flash memory bank to XDATA address 0x8000-0xFFFF
    write_xdata_memory(DUP_MEMCTR, address >> 15);
    # 2. Move data pointer to XDATA address (MOV DPTR, xdata_addr)
    debug_command(0x57_90_0000 | 0x8000 | (address & 0x7fff))
    for i in range(len(buffer)):
        # 3. MOVX A, @DPTR
        buffer[i] = debug_command(0x55_E0_0000)
        # 4. INC DPTR
        debug_command(0x55_A3_0000)


def prepare_for_writing():
    print("status before erase", end='  ');  print("%02X" % (debug_command(0x30_000000)) )
    debug_command(0x10_000000)          # CMD_CHIP_ERASE
    print("Waiting for erase end", end='')
    while (debug_command(0x30_000000) & 0x80):
        time.sleep(0.5)
        print(".", end='')
        # wait for STATUS_CHIP_ERASE_BUSY_BM flag go low in CMD_READ_STATUS
        pass
    print("\nEnablind DMA")
    debug_command(0x19_22_0000)         # enable DMA: CMD_WR_CONFIG 0x22


def write_flash_memory_block(address, buffer):
    buflen = len(buffer)
    # 1. Write the 2 DMA descriptors to RAM
    dma_desc_0 = bytes([
        HIBYTE(DUP_DBGDATA), LOBYTE(DUP_DBGDATA),
        HIBYTE(ADDR_BUF0),   LOBYTE(ADDR_BUF0),
        HIBYTE(buflen),      LOBYTE(buflen),
        0x1f, 0x11 ])
    dma_desc_1 = bytes([
        HIBYTE(ADDR_BUF0),   LOBYTE(ADDR_BUF0),
        HIBYTE(DUP_FWDATA),  LOBYTE(DUP_FWDATA),
        HIBYTE(buflen),      LOBYTE(buflen),
        0x12, 0x42 ])

    write_xdata_memory_block(ADDR_DMA_DESC_0, dma_desc_0);
    write_xdata_memory_block(ADDR_DMA_DESC_1, dma_desc_1);


    # 3. Set DMA controller pointer to the DMA descriptors
    write_xdata_memory(DUP_DMA0CFGH, HIBYTE(ADDR_DMA_DESC_0))
    write_xdata_memory(DUP_DMA0CFGL, LOBYTE(ADDR_DMA_DESC_0))
    write_xdata_memory(DUP_DMA1CFGH, HIBYTE(ADDR_DMA_DESC_1))
    write_xdata_memory(DUP_DMA1CFGL, LOBYTE(ADDR_DMA_DESC_1))

    # 4. Set Flash controller start address (wants 16MSb of 18 bit address)
    write_xdata_memory(DUP_FADDRH, HIBYTE( (address >> 2) ))
    write_xdata_memory(DUP_FADDRL, LOBYTE( (address >> 2) ))

    # 5. Arm DBG=>buffer DMA channel and start burst write
    write_xdata_memory(DUP_DMAARM, CH_DBG_TO_BUF0)
    burst_write_block(buffer)

    # 6. Start programming: buffer to flash
    write_xdata_memory(DUP_DMAARM, CH_BUF0_TO_FLASH)
    write_xdata_memory(DUP_FCTL, 0x06)

    # 7. Wait until flash controller is done
    while (read_xdata_memory(DUP_FCTL) & 0x80):
        pass
