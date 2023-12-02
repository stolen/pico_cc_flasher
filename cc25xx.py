import rp2pio
import adafruit_pioasm
from array import array
import board
import time

SM_DEBUG_INIT   = 1
SM_DEBUG_CMD    = 2

sm = None
loaded_sm = None
debug_inited = False

pinDD  = board.GP27
# DC and RST must be consecutive because they are set by pio side-set
pinDC  = board.GP28
pinRST = board.GP29

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
.wrap_target
    pull                            ; wait for next command, ensure clock low

    mov y osr                       ; store command in Y
    jmp !y read_byte           ; if command is zero, just receive byte

    set pindirs 1       side 2      ; DD output
    set y 5                         ; just send first 6 bits (MSb)
cmd6_cont:
    mov isr null        side 2  [0] ; compensate for LSb processing while resetting ISR
    out pins, 1         side 3  [1] ; set data bit, clock high
    jmp y-- cmd6_cont   side 2      ; clock low

    out x, 1            side 2      ; X = CMD_bit1
    in x, 1             side 2      ; ISR = CMD_bit1
    mov pins x          side 3      ; DD = X, clock high

    out x, 1                        ; X = CMD_bit0, clock low
    in x, 1             side 2  [1] ; ISR = [...... CMD_bit1 CMD_bit0]
    mov pins x          side 3  [1] ; DD = X, clock high
    mov x isr           side 2  [0] ; X is lower 2 bits of command = number of data bytes, clock low

data_byte:
    jmp !x wait_ready   side 2      ; X = 0 means no more data to send; clock low
    set y 6             side 2  [1] ; 7 data bits are just sent
data_bit:
    out pins, 1         side 3      ; set data bit, clock high
    jmp y-- data_bit    side 2  [2] ; clock low and move to next bit (if any)

    out pins, 1         side 3      ; set last data bit, clock high
    jmp x-- data_byte   side 3      ; X is always non-zero, decrement and jump

wait_ready:
    set pindirs 0       side 2  [3] ; DD input next instruction after clock low
read_byte:
    mov isr null
    in pins, 1
    ; mov x, isr          side 2      ; X stores DUP non-readiness before this strobe
just_read_byte:
    set y 6             side 2      ; 7 bits
read_bit:
    nop                 side 3  [1] ; DUP sets bit at rising clock edge, let it settle
    in pins, 1          side 2      ; read at falling clock edge
    jmp y-- read_bit    side 3

    nop                         [1]
    in pins, 1          side 2      ; read at falling clock edge

    ; jmp x-- read_byte   side 2      ; if DUP was not ready (DD high), read next byte
    push                side 2
.wrap

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
        frequency = 25*1000_000,    # seems like RP2040 cannot switch output to input faster.
                                    # Maybe with second input-only pin on DD reads will be more reliable
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
    return read_chip_id()

def read_chip_id():
    # read ChipID
    (drop, chip_id) = debug_command(0x68000000)
    (drop, chip_rev) = debug_command(0)

    chip_name = "Unknown"
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

    return (chip_id, chip_name, chip_rev)


def debug_command(cmd):
    global sm

    buf = array("L", [cmd])

    sm.clear_rxfifo()
    sm.background_write(buf)
    started_at = time.monotonic_ns()
    while sm.in_waiting == 0:
        if time.monotonic_ns() - started_at > 30_000_000_000: # 30 seconds
            sm.clear_txstall()
            sm.restart()
            return None
    sm.readinto(buf)
    return (buf[0] >> 8, buf[0] & 0xff)


ensure_sm(SM_DEBUG_CMD, debug_command_prog)
