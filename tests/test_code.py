#%%
import dlpyc900.dlpyc900 as dlpyc900

import numpy
# import PIL.Image

#%% test reading some properties
dlp=dlpyc900.dmd()
print(dlp.get_display_mode())
print(f"DMD model is {dlp.get_hardware()[0]}")
print(dlp.get_main_status())
print(dlp.get_hardware_status())
print(dlp.get_current_powermode())

#%% setup video mode
dlp.set_display_mode('video')
dlp.set_dual_pixel_mode()
dlp.set_display_to_parallel()
dlp.lock_displayport()
print(f"locked to source [{dlp.check_source_lock()}]")

#%% Video-pattern setup

dlp.set_display_mode('video-pattern')
dlp.setup_pattern_LUT()
dlp.start_pattern()