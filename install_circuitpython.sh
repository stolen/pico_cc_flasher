#!/bin/bash
FLASHNUKE_URL="https://cdn-learn.adafruit.com/assets/assets/000/099/419/original/flash_nuke.uf2"
FLASHNUKE_SIZE=25600
CIRCUITPYTHON_URL="https://downloads.circuitpython.org/bin/waveshare_rp2040_zero/en_US/adafruit-circuitpython-waveshare_rp2040_zero-en_US-8.2.8.uf2"
CIRCUITPYTHON_SIZE=1516032

# Assume CircuitPython always has '2040' substring in device id
[ -n "$(ls /dev/disk/by-id/usb-*2040*-part1 2>/dev/null)" ] && 
    { echo "Found RP2040 in normal mode. Please restart it in bootloader mode." >&2; exit 1; }

# Resolve RP2 bootloader label into a mount point. `findmnt` seems to be installed by default on Ubuntu
MOUNTPOINT=${MOUNTPOINT:-$(findmnt --noheadings --raw --output target --source LABEL=RPI-RP2)}
if [[ $? -ne 0 ]]; then
    DEV=$(readlink -f /dev/disk/by-label/RPI-RP2)
    # Less reliable way using more common utilities
    MOUNT="$(fgrep --max-count=1 $DEV /proc/mounts)"
    [[ $? -eq 0 ]] || { echo "Cannot find mountpoint for $DEV" >&2; exit 1; }
    MOUNTPOINT=$(echo $MOUNT | cut -d ' ' -f 2 | head -1)
fi

echo "RP2 at $MOUNTPOINT"

echo "Preparing UF2 images"

FLASHNUKE_CACHE=cache/flash_nuke.uf2
[[ $(stat --format "%s" $FLASHNUKE_CACHE) -eq $FLASHNUKE_SIZE ]] ||
    wget --continue --output-document $FLASHNUKE_CACHE $FLASHNUKE_URL || exit 2

CIRCUITPYTHON_CACHE=cache/circuitpython.uf2
[[ $(stat --format "%s" $CIRCUITPYTHON_CACHE) -eq $CIRCUITPYTHON_SIZE ]] ||
    wget --continue --output-document $CIRCUITPYTHON_CACHE $CIRCUITPYTHON_URL || exit 2

UF2LOCK=$MOUNTPOINT/lock

touch $UF2LOCK
echo -n "Erasing all data on your RP2"
cp $FLASHNUKE_CACHE $MOUNTPOINT/
for i in $(seq 1 30); do
    [ -f $UF2LOCK ] || break
    echo -n '.'
    sleep 1
done
echo
[ -f $UF2LOCK ] && { echo "RP2 did not restart to install UF2 image" >&2; exit 3; }

echo -n "Waiting for clean RP2 to reappear mounted"
for i in $(seq 1 60); do
    [ -f $MOUNTPOINT/INFO_UF2.TXT ] && break
    echo -n .
    sleep 1
done
echo
[ -f $MOUNTPOINT/INFO_UF2.TXT ] || { echo "RP2 did not come back clean" >&2; exit 3; }


touch $UF2LOCK
echo -n "Installing CircuitPython"
cp $CIRCUITPYTHON_CACHE $MOUNTPOINT/
for i in $(seq 1 30); do
    [ -f $UF2LOCK ] || break
    echo -n '.'
    sleep 1
done
echo
[ -f $UF2LOCK ] && { echo "RP2 did not restart to install UF2 image" >&2; exit 3; }

echo -n "Waiting for CircuitPython to deploy"
for i in $(seq 1 60); do
    [ -n "$(ls /dev/disk/by-id/usb-*2040*-part1 2>/dev/null)" ] && break
    echo -n .
    sleep 1
done
echo -n " "
DEV=$(readlink -f /dev/disk/by-id/usb-*2040*-part1 | head -1)
[ -e $DEV ] || { echo "CircuitPython did not appear at $DEV" >&2; exit 3; }
for i in $(seq 1 15); do
    fgrep -q $DEV /proc/mounts && break
    echo -n .
    sleep 1
done
echo
fgrep -q $DEV /proc/mounts || { echo "CircuitPython dev $DEV was not mounted" >&2; exit 3; }

echo "CircuitPython was installed successfully"
