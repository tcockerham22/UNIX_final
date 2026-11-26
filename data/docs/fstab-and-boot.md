# Filesystems, fstab, and the Boot Process

When a Linux machine boots, the firmware starts a bootloader, the bootloader starts the kernel, and the kernel starts the init system. On most modern distributions the init system is systemd, which brings up services in dependency order.

## Mounting filesystems

A filesystem on a disk or logical volume becomes usable only after it is mounted on a directory, called the mount point. The mount command attaches a filesystem, and umount detaches it. The command findmnt lists what is mounted where, and mountpoint -q tests whether a directory is currently a mount point.

## The /etc/fstab file

The file /etc/fstab lists filesystems that should be mounted automatically at boot. Each line has six fields: the device or UUID, the mount point, the filesystem type, the mount options, the dump flag, and the fsck pass number. Using UUID=... instead of a device name such as /dev/sdb is safer, because device names can change between boots while UUIDs stay the same. The command blkid prints the UUID of a formatted volume.

## Useful mount options

The option defaults selects a standard set of options. The option nofail tells the system not to stop booting if the device is missing, which is valuable on cloud machines where an attached disk may be late. After editing /etc/fstab, running mount -a mounts every entry that is not already mounted and quickly reveals typos before the next reboot.

## Idempotent scripts

An idempotent script can be run many times and always ends in the same state. A startup script that runs on every boot must check before it acts. It should create a logical volume only if that volume does not exist, add an fstab line only if the line is missing, and mount a directory only if it is not already mounted. Idempotency is what allows a machine to reboot without being rebuilt.

## Why the mount order matters

A service that stores data in a directory must start after the filesystem is mounted there. If a container starts first, it may write into an empty directory on the root disk, and the real data appears to be missing until the correct volume is mounted over it.
