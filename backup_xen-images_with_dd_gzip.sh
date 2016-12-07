#!/bin/bash

dir=/data/backup/server/xen/vms/$(date +%F)

mkdir -p $dir
for i in $(ls /dev/system/xm* | grep -v swap); do
    lvcreate -s -L 1G -n $(basename $i)-snapshot $i
    dd bs=1M if=${i}-snapshot | gzip -c - > $dir/$(basename $i).img.gz
    lvremove -f ${i}-snapshot
done
