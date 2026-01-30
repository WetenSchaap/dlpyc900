"""
Example of how to use this code to make the DMD show uploaded images in on-the-fly mode
"""
#%% Connect & test reading some properties
import dlpyc900
import PIL.Image

dlp=dlpyc900.dmd()
print(dlp.get_display_mode())
print(f"DMD model is {dlp.get_hardware()[0]}")
print(dlp.get_main_status())
print(dlp.get_hardware_status_for_humans())
print(f"power moder is '{dlp.get_current_powermode()}'")

#%% set to otf mode and prepare patterns
dlp.set_input_source(2)     # set image source to the flash memory
dlp.set_display_mode("otf") # otf = on-the-fly mode

dlp.setup_pattern_LUT_definition(
    pattern_index=0,              # position in memory to save this pattern
    exposuretime= round( 2*1e6 ), # time in microseconds
    darktime = round( 1*1e6 ),    # time to stay dark after exposure 
    bitdepth=8,
    color=7,                      # color 7 = all LEDs
    image_pattern_index=0         # index of the image to display
)

dlp.setup_pattern_LUT_definition(
    pattern_index=1,              # position in memory to save this pattern
    exposuretime= round( 4*1e6 ), # time in microseconds
    darktime = round( 2*1e6 ),    # time to stay dark after exposure 
    bitdepth=8,
    color=7,                      # color 7 = all LEDs
    image_pattern_index=1         # index of the image to display
)

# Configure LUT pattern
dlp.configure_pattern_from_LUT(
    nr_of_LUT_entries=2,          # There are 2 LUT entries defined above 
    nr_of_patterns_to_display=0   # 0=infinite loop, 4 means cycle trough the LUT entries, with a total of 4 steps. So if there are 2 LUT entries, you show each entry *twice*. It cycles from 0 to 1, to 2, to 3, etc. Just sequential.
)

#%% Upload images to DMD:
im1 = PIL.Image.open("../idle-mode.png")
im1 = im1.convert("RGB") # images have to be in RGB format to work!
im2 = PIL.Image.open("./usb-transaction-seq.png")
im2 = im2.convert("RGB")

dlp.upload_image(
    1,      # this is the image_pattern_index, the location the image is saved, as given in setup_pattern_LUT_definition. Positions 0 to 17 are available. Always start filling from high to low, so first 17, then 16, then 15, etc.
    im2,    # the image to upload
    False   # whether you have a dual-controller DMD. Depends on the model, you can check with get_hardware_status_for_humans(). If yes, the image is split, and half is uploaded to one controller, the other half to the other.
)


dlp.upload_image(
    0,      # this is the image_pattern_index, the location the image is saved, as given in setup_pattern_LUT_definition. Positions 0 to 17 are available. Always start filling from high to low, so first 17, then 16, then 15, etc.
    im1,    # the image to upload
    False   # whether you have a dual-controller DMD. Depends on the model, you can check with get_hardware_status_for_humans(). If yes, the image is split, and half is uploaded to one controller, the other half to the other.
)

#%% And start the pattern:

dlp.start_pattern()

#%% Stop pattern when you are sick of this.

dlp.stop_pattern()
