import rp2pio
import adafruit_pioasm
import array
import board

SM_DEBUG_INIT   = 1
SM_DEBUG_CMD    = 2

sm = None
loaded_sm = None

pinDD  = board.GP20
# DC and RST must be consecutive because they are set by pio side-set
pinDC  = board.GP21
pinRST = board.GP20

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
.side_set 2
start:
    pull                side 2      ; wait for next command, ensure clock low

    mov y osr           side 2
    jmp !y wait_ready   side 2      ; if input word is NULL, just read one more byte

    set pindirs 1       side 2      ; DD output
    set y 5                         ; just send first 6 bits (MSb)
cmd6_cont:
    mov isr null        side 2  [1] ; compensate for LSb processing while resetting ISR
    out pins, 1         side 3      ; set data bit, clock high
    jmp y-- cmd6_cont   side 2      ; clock low

    out x, 1            side 2      ; X = CMD_bit1
    in x, 1             side 2      ; ISR = CMD_bit1
    mov pins x          side 3      ; DD = X, clock high

    out x, 1            side 2      ; X = CMD_bit0, clock low
    in x, 1             side 2  [1] ; ISR = [...... CMD_bit1 CMD_bit0]
    mov pins x          side 3      ; DD = X, clock high
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
    set pindirs 0       side 2      ; DD input next instruction after clock low
read_byte:
    set y 7             side 2      ; 8 bits
read_bit:
    nop                 side 3  [1] ; DUP sets bit at rising clock edge, let it settle
    in pins, 1          side 2      ; read at falling clock edge
    jmp y-- read_bit    side 2

    nop                 side 2  [3]
    jmp pin read_byte   side 2      ; while pin is high, read one more byte

    push                side 2
    jmp start           side 2
"""
# Tdir_change is 83 ns, ~0.1us -- may use any speed because 4 ticks are always more
debug_command_compiled = adafruit_pioasm.assemble(debug_command_asm)


ping_asm = """
.program ping
.side_set 2
start:
    nop     side 3
    pull    side 2
    mov isr osr side 3
    push    side 2
    jmp start
"""
ping_compiled = adafruit_pioasm.assemble(ping_asm)

test_asm = """
.program test
.side_set 2
start:
    set pins, 1     side 3
    set pins, 0     side 0
    jmp start
"""
test_compiled = adafruit_pioasm.assemble(test_asm)

test2_asm = """
.program test
.side_set 2
    set pindirs, 1      side 1
start:
    set pins, 1         side 2
    set pins, 0         side 3
    jmp start           side 0
"""
test2_compiled = adafruit_pioasm.assemble(test2_asm)

def ensure_sm(sm_id, compiled):
    global loaded_sm, sm
    global pinRST, pinDD, pinDC
    if loaded_sm == sm_id:
        return loaded_sm
    sm = rp2pio.StateMachine(
        compiled,
        frequency = 25*1000,

        first_set_pin = pinDD,
        #initial_set_pin_direction = 0,

        first_out_pin = pinDD,
        out_pin_count = 1,
        #initial_out_pin_direction = 0,   # for pull-up
        #initial_out_pin_state = 0,

        first_in_pin = pinDD,
        #in_pin_count = 1,
        #pull_in_pin_up = True,

        jmp_pin = pinDD,

        sideset_enable = False,             # This really means 'sideset_optional' -- extra bit
        first_sideset_pin = pinDC,          # second is pinRST
        sideset_pin_count = 2,
        initial_sideset_pin_state = 2,      # DC low, RST high
        initial_sideset_pin_direction = 0x1f,

        auto_pull = False,
        auto_push = False,
        out_shift_right = False,
        in_shift_right = False,

        user_interruptible = True
    )

