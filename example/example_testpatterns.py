"""
Example of how to use this code to make the DMD show some built-in test patterns.
"""
#%% test reading some properties
import dlpyc900

dlp=dlpyc900.dmd()
print(dlp.get_display_mode())
print(f"DMD model is {dlp.get_hardware()[0]}")
print(dlp.get_main_status())
print(dlp.get_hardware_status_for_humans())
print(f"power moder is '{dlp.get_current_powermode()}'")

#%% Show a test pattern

dlp.select_test_pattern(7) # 7 is a checkerboard, check docstring of function for other test patterns
dlp.set_test_pattern_colors(
    (1023,1023,1023), # this is the forground color in RGB, with each color a value between 0 and 1023. So here we show white.
    (0,0,0)           # this is the background color, idem.
) 
dlp.set_input_source(1) # activate the test pattern view

#%% Different test pattern

dlp.select_test_pattern(1) # 1 is a horizontal ramp

#%% Show the curtain (just a solid color)

dlp.set_curtain_color((0,0,0)) # color of the curtain, defined as above in set_test_pattern_colors. This is just black.
dlp.set_input_source(3) # activate the curtain view
