# dlpyc900

This is a Python module for controlling Texas-instrument DMD's with a DLPC900 controller, based on the USB-interface described in the [user manual](https://www.ti.com/lit/ug/dlpu018j/dl).

## Example code

Below some random commands you can give.

``` python
import dlpyc900
dlp = dlpyc900.dmd()           # open connection
print(f"DMD model is {dlp.get_hardware()[0]}")
print(dlp.get_main_status())   # Check if all is ok with the device
dlp.set_display_mode('video')  # Set display mode to video
dlp.set_port_clock_definition(2,0,0,0) # Dual pixel mode
dlp.set_input_source(0,0)      # Switch to parallel interface input source
dlp.lock_displayport()         # Lock to the displayport input source
dlp.standby()                  # go into standby mode
# etc. etc.
```

Note that *not all commands are available via the module yet*. I can do what I want (that is, using the DMD as a videoprojector basically), so expanding this module further is a waste of time for me. However, if you can do some programming, it should be relatively straightforward to add new commands ([see here](./example/readme.md), contributions are welcome!), or you can ask me to implement them by opening an issue.

## Supported models

I only use the DLP9000 DMD, but in principle at least the following DMDs should also be supported:

- DLP6500
- DLP9000
- DLP670S
- DLP500YX
- DLP5500

## Installation

First, install this module in your Python enviroment. This module is not in the pypi repository (yet), so you can install it directly from github using `pip`, `poetry`, or whatever tool you use. The main dependency of this module is the `pyusb` module.

After that, you need to install new drivers for the DMD device. 

1. Install and open [Zadig](https://zadig.akeo.ie/).
2. Plug in the usb cable of the DMD.
3. Select "List all devices" in Zadig.
4. Select `DLPC900` from the list of devices.
5. Selected the "libusb-win32" driver.
6. Pressed the "Replace driver" button, wait for install to complete.
7. And now try using the module, things should work!

Note that replacing the driver will make the normal GUI not work anymore! Luckily, you can re-install the old driver any time you want:

1. With the projector connected over USB, to go to device manager.
2. Uninstall the device connected using the libusb driver; when the confirmation window comes up, make sure to check the box to also remove driver software.
3. Unplug and replug the USB cable.
4. The old 'regular' drivers will now be installed, and the GUI can be used again.

## Credits

I forked this module from the code from [ppozzi](https://github.com/csi-dcsc/Pycrafter6500), but I added quite a few extra functions which I needed, and added a lot of documentation. I removed the on-the-fly capabilities, because I dod not want to spend time understanding them, and I did not need them, but they should be easy to re-add.