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
dlp.set_port_clock_definition(2,0,0,0)
dlp.set_input_source(0,0)
dlp.lock_displayport()
print(f"locked to source [{dlp.get_source_lock()}]")

#%% Video-pattern setup

dlp.set_display_mode('video-pattern')
dlp.setup_pattern_LUT_definition(
    pattern_index=0, exposuretime=15000, darktime=0, bitdepth=8, bit_position=0
)
dlp.start_pattern_from_LUT(nr_of_LUT_entries = 1, nr_of_patterns_to_display = 0)
dlp.start_pattern()