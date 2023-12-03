#!/bin/bash
COMMAND="$0 $@"

# mountpoint may be passed as a first argument
if [[ -n $1 ]]; then
    [[ -d $1 ]] || { echo "Specified path $1 is not a directory" >&2; exit 1; }
    MOUNTPOINT=$1
else
    # Assume CircuitPython always has '2040' substring in device id
    DEV=$(readlink -f /dev/disk/by-id/usb-*2040*-part1 | head -1)
    [ -e $DEV ] || { echo "Cannot find CircuitPython MSC at $DEV" >&2; exit 1; }

    # Resolve device into a mount point. `findmnt` seems to be installed by default on Ubuntu
    MOUNTPOINT=${MOUNTPOINT:-$(findmnt --noheadings --raw --output target --source $DEV)}
    if [[ $? -ne 0 ]]; then
        # Less reliable way using more common utilities
        MOUNT="$(fgrep --max-count=1 $DEV /proc/mounts)"
        [[ $? -eq 0 ]] || { echo "Cannot find mountpoint for $DEV" >&2; exit 1; }
        MOUNTPOINT=$(echo $MOUNT | cut -d ' ' -f 2 | head -1)
    fi
fi

echo "Discovered RP2040 storage at $MOUNTPOINT"

if [ -z $COMPILE ]; then
    COMPILE=n
    mpy-cross --version &>/dev/null && COMPILE=y
fi
[[ $COMPILE == y ]] && echo "Will compile"

function install_py {
    src=$1
    dst=$2/$(basename $src)
    if [[ $COMPILE == y ]]; then
        dst=${dst%.py}.mpy
        echo "compile-install $src -> $dst"
        mpy-cross -o $dst $src
        [[ $? -eq 0 ]] || { echo "Cannot compile $src. Try running \"COMPILE=n $COMMAND\"" >&2; exit 1; }
    else
        cp -v $src $dst
    fi
}

LIB_DIR=$MOUNTPOINT/lib
[ -d $LIB_DIR ] || mkdir $LIB_DIR
for src in cc25xx_*.py hex_reader.py lib/*.py; do
    install_py $src $LIB_DIR
done
for script in code.py boot.py; do
    cp -v $script $MOUNTPOINT/
done

echo SUCCESS!
