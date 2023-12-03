Standalone TI CC25xx flasher
=======================================================
Project home: https://github.com/stolen/pico_cc_flasher

What is this?
-------------------------------------------------------
This is a simple to use programmer designed to run
on Waveshare RP2040-Zero (but not limited to it).
Any RP2040 board should work.

Wiring
-------------------------------------------------------

RP2040              CC2531
                                  | [2531]     [sw] |
                                  | [    ]          |
GND        ->        GND  (1)     |        [*1  2 ] |
3V3   - optional ->  3V3  (9)     |        [*3  4*] |
GP29       ->        nRST (7)     |          5  6 ] |
GP28       ->        DC   (3)     |  [sw]  [*7  8 ] |
GP27       ->        DD   (4)     |        [?9  10] |
                                  |                 |
                                  +----[ U S B ]----+

Using
-------------------------------------------------------
 > Open 'cc25xx' directory
 > There may be a file named 'data.read.bin'
    It contains a flash dump
    Remove the 'control.skip_flash_read' file to re-read
 > Drop a '*.hex' or '*.bin' file into this directory
    to flash it.
