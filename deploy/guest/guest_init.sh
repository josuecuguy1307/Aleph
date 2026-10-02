#!/bin/sh
# One-shot trusted provisioning probe. No network/storage/shared-directory devices.
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mkdir -p /tmp
mount -t tmpfs -o size=128m tmpfs /tmp
echo ALEPH_GUEST_BOOTED >/dev/hvc0
if ! apk --repositories-file /dev/null add --no-network --force-non-repository /packages/*.apk >/tmp/aleph-apk.log 2>&1; then
  cat /tmp/aleph-apk.log >/dev/hvc0
  echo ALEPH_GUEST_APK_FAILED >/dev/hvc0
  exec /bin/sh </dev/hvc0 >/dev/hvc0 2>&1
fi
exec python3 -I /opt/aleph/runner.py </dev/hvc0 >/dev/hvc0 2>&1
