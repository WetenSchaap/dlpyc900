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
dlp.check_system_status()
dlp.check_communication_status()
#%%
dlp.set_display_mode('pattern')


#%%

images=[]

images.append((numpy.asarray(PIL.Image.open("testimage.tif"))//129))

dlp=dlpyc900.dmd()

dlp.stopsequence()

dlp.changemode(3)

exposure=[1000000]*30
dark_time=[0]*30
trigger_in=[False]*30
trigger_out=[1]*30

dlp.defsequence(images,exposure,trigger_in,dark_time,trigger_out,0)

dlp.startsequence()
