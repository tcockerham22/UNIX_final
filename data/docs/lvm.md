# Logical Volume Manager (LVM)

LVM is a Linux layer that sits between physical disks and the filesystems on top of them. Instead of formatting a whole disk or a fixed partition, an administrator builds flexible storage out of three layers: physical volumes, volume groups, and logical volumes.

## The three layers

A physical volume (PV) is a disk or partition that has been handed to LVM. The command pvcreate initializes a device as a physical volume. A volume group (VG) is a pool of storage built from one or more physical volumes. The command vgcreate creates a volume group from the listed physical volumes. A logical volume (LV) is a slice of the pool that behaves like a disk partition. The command lvcreate creates a logical volume of a requested size inside a volume group, for example lvcreate -L 10G -n lv_db vg_data.

## Using a logical volume

A new logical volume has no filesystem. The administrator formats it, for example with mkfs.ext4, and then mounts it on a directory. The device path looks like /dev/vg_data/lv_db. To make the mount survive reboots, a line is added to the file /etc/fstab.

## Inspecting LVM

The commands pvs, vgs, and lvs print short summaries of physical volumes, volume groups, and logical volumes. The longer forms pvdisplay, vgdisplay, and lvdisplay show full details. The command lsblk shows the block device tree, including logical volumes, and df -h shows how full each mounted filesystem is.

## Why use LVM

Logical volumes can be grown while the system is running. The command lvextend enlarges a logical volume, and resize2fs then grows an ext4 filesystem to fill it. Several logical volumes can share one disk, so a database volume and a model-files volume can be sized independently and kept separate. Leaving some free space in the volume group is important, because snapshots and later growth both draw from that free space.

## Common mistakes

Running pvcreate on the wrong device destroys the data on it, so always confirm the device name with lsblk first. Allocating every extent in the volume group leaves no room for snapshots. Forgetting the /etc/fstab entry means the volume is not mounted after a reboot, and a service that expects its data directory may then silently start with an empty folder on the root disk.
