# Storage, timezone and administrator creation remain interactive.
graphical
lang en_US.UTF-8
keyboard us
network --bootproto=dhcp --device=link --activate --onboot=on
rootpw --lock
reboot
# The build replaces this with the exact verified bootstrap digest.
bootc --source-imgref containers-storage:@PAYLOAD@ --target-imgref @PAYLOAD@
